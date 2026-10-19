"""Painel web local (FastAPI + Jinja2 + HTMX)."""
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from contextlib import asynccontextmanager
import time

from . import companies, db, llm, pipeline, resume
from .config import CFG

_task_state = {"running": False, "message": "", "last_sync": ""}


def _run_sync(avaliar: bool = True, limit: int = 15):
    if _task_state["running"]:
        return
    _task_state["running"] = True
    try:
        _task_state["message"] = "Coletando vagas nas empresas..."
        con = db.connect()
        if not con.execute("SELECT 1 FROM companies LIMIT 1").fetchone():
            companies.import_all(con, verbose=False)
        new = pipeline.collect(con)
        if avaliar and llm.available() and new > 0:
            _task_state["message"] = f"{new} vagas novas. Avaliando com a IA..."
            pipeline.evaluate(con, limit=limit)
        _task_state["last_sync"] = db.now()
        _task_state["message"] = f"Concluído ({new} vagas novas)."
    except Exception as e:
        _task_state["message"] = f"Erro: {e}"
    finally:
        _task_state["running"] = False


def _auto_scheduler_loop(hours: float):
    interval_sec = max(1800, int(hours * 3600))
    while True:
        time.sleep(interval_sec)
        _run_sync(avaliar=True, limit=15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hours = float(CFG.get("coleta", {}).get("auto_horas", 6))
    if hours > 0:
        threading.Thread(target=_auto_scheduler_loop, args=(hours,), daemon=True).start()
    yield


app = FastAPI(title="Vagas Hunter", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def _query_jobs(con, q: str = "", status: str = "ativas", min_score: int = 0, company_id: int = 0, only_scored: bool = False):
    sql = """
        SELECT j.*, c.name AS company_name, c.ats AS company_ats, c.slug AS company_slug
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.open = 1
    """
    params = []

    if status == "ativas":
        sql += " AND j.status != 'descartada'"
    elif status != "todas":
        sql += " AND j.status = ?"
        params.append(status)

    if min_score > 0:
        sql += " AND COALESCE(j.score, -1) >= ?"
        params.append(min_score)

    if only_scored:
        sql += " AND j.score IS NOT NULL"

    if company_id > 0:
        sql += " AND j.company_id = ?"
        params.append(company_id)

    if q.strip():
        term = f"%{q.strip()}%"
        sql += " AND (j.title LIKE ? OR c.name LIKE ? OR j.description LIKE ? OR j.reason LIKE ?)"
        params.extend([term, term, term, term])

    sql += """
        ORDER BY
            CASE WHEN j.score IS NOT NULL THEN 0 ELSE 1 END,
            COALESCE(j.score, 0) DESC,
            COALESCE(j.stage1, 0) DESC,
            j.first_seen DESC
        LIMIT 250
    """
    return con.execute(sql, params).fetchall()


def _stats(con):
    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
            SUM(CASE WHEN score >= 70 AND status != 'descartada' THEN 1 ELSE 0 END) AS high_match,
            SUM(CASE WHEN status = 'nova' THEN 1 ELSE 0 END) AS novas,
            SUM(CASE WHEN status = 'interessa' THEN 1 ELSE 0 END) AS interessa,
            SUM(CASE WHEN status = 'candidatei' THEN 1 ELSE 0 END) AS candidatei,
            SUM(CASE WHEN status = 'descartada' THEN 1 ELSE 0 END) AS descartadas
        FROM jobs WHERE open = 1
    """).fetchone()
    comp_count = con.execute("SELECT COUNT(*) FROM companies WHERE active = 1").fetchone()[0]
    return {**(dict(row) if row else {}), "companies": comp_count}


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = Query(""),
    status: str = Query("ativas"),
    min_score: int = Query(0),
    company_id: int = Query(0),
    only_scored: bool = Query(False),
):
    con = db.connect()
    jobs = _query_jobs(con, q=q, status=status, min_score=min_score, company_id=company_id, only_scored=only_scored)
    stats = _stats(con)
    comps = con.execute(
        "SELECT c.id, c.name, c.ats, COUNT(j.id) AS job_count "
        "FROM companies c LEFT JOIN jobs j ON j.company_id = c.id AND j.open = 1 "
        "WHERE c.active = 1 GROUP BY c.id ORDER BY c.name"
    ).fetchall()
    try:
        prof = resume.get_profile() if (resume.CACHE.exists()) else {}
    except Exception:
        prof = {}

    ctx = {
        "request": request,
        "jobs": jobs,
        "stats": stats,
        "companies": comps,
        "profile": prof,
        "ollama_ok": llm.available(),
        "task": _task_state,
        "filters": {
            "q": q,
            "status": status,
            "min_score": min_score,
            "company_id": company_id,
            "only_scored": only_scored,
        },
    }
    if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "jobs-container":
        return templates.TemplateResponse(request, "_jobs_list.html", ctx)
    return templates.TemplateResponse(request, "index.html", ctx)


@app.post("/jobs/{job_id}/status", response_class=HTMLResponse)
def update_job_status(request: Request, job_id: str, status: str = Form(...)):
    allowed = {"nova", "interessa", "candidatei", "descartada"}
    if status not in allowed:
        return HTMLResponse("Status inválido", status_code=400)
    con = db.connect()
    con.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    con.commit()
    job = con.execute(
        "SELECT j.*, c.name AS company_name, c.ats AS company_ats, c.slug AS company_slug "
        "FROM jobs j JOIN companies c ON c.id = j.company_id WHERE j.id = ?",
        (job_id,),
    ).fetchone()
    return templates.TemplateResponse(request, "_job_card.html", {"request": request, "j": job})


@app.post("/jobs/{job_id}/avaliar", response_class=HTMLResponse)
def evaluate_single_job(request: Request, job_id: str):
    con = db.connect()
    r = con.execute(
        "SELECT j.*, c.name AS company_name, c.ats AS company_ats, c.slug AS company_slug "
        "FROM jobs j JOIN companies c ON c.id = j.company_id WHERE j.id = ?",
        (job_id,),
    ).fetchone()
    if not r:
        return HTMLResponse("Vaga não encontrada", status_code=404)

    profile = resume.get_profile()
    desc = r["description"] or ""
    candidate = (
        f"Senioridade: {profile.get('senioridade')}\nCargos: {', '.join(profile.get('cargos', []))}\n"
        f"Skills: {', '.join(profile.get('skills', []))}\n\nCURRÍCULO:\n{profile.get('_texto', '')[:3500]}"
    )
    job_txt = f"VAGA: {r['title']}\nEmpresa: {r['company_name']}\nLocal: {r['location']}\n\n{desc[:5000]}"
    res = llm.chat_json(matching_system(), f"CANDIDATO\n{candidate}\n\n---\n\n{job_txt}")
    from . import matching
    nota, level_ok = matching.compute_score(res, profile.get("senioridade", "junior"))
    missing = res.get("skills_faltando") or []
    con.execute(
        "UPDATE jobs SET score=?, reason=?, missing=?, seniority_ok=?, scored_at=? WHERE id=?",
        (nota, f"[{res.get('nivel_vaga', '?')}] {res.get('motivo', '')}",
         ", ".join(map(str, missing[:6])), int(level_ok), db.now(), job_id),
    )
    con.commit()
    job = con.execute(
        "SELECT j.*, c.name AS company_name, c.ats AS company_ats, c.slug AS company_slug "
        "FROM jobs j JOIN companies c ON c.id = j.company_id WHERE j.id = ?",
        (job_id,),
    ).fetchone()
    return templates.TemplateResponse(request, "_job_card.html", {"request": request, "j": job})


def matching_system() -> str:
    from . import matching
    return matching.SYSTEM


@app.post("/acoes/coletar")
def trigger_collect(avaliar: bool = Form(True)):
    if _task_state["running"]:
        return JSONResponse({"status": "already_running", "message": _task_state["message"]})

    def _worker():
        _task_state["running"] = True
        try:
            _task_state["message"] = "Coletando vagas nas empresas..."
            con = db.connect()
            new = pipeline.collect(con)
            if avaliar and llm.available():
                _task_state["message"] = f"{new} vagas novas. Avaliando com a IA local..."
                pipeline.evaluate(con, limit=15)
            _task_state["message"] = f"Concluído ({new} vagas novas)."
        except Exception as e:
            _task_state["message"] = f"Erro: {e}"
        finally:
            _task_state["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse({"status": "started", "message": "Coleta iniciada em segundo plano."})


@app.post("/acoes/avaliar")
def trigger_evaluate(limite: int = Form(15)):
    if _task_state["running"]:
        return JSONResponse({"status": "already_running", "message": _task_state["message"]})

    def _worker():
        _task_state["running"] = True
        try:
            _task_state["message"] = f"Avaliando até {limite} vagas com o Ollama..."
            con = db.connect()
            n = pipeline.evaluate(con, limit=limite)
            _task_state["message"] = f"Concluído ({n} vagas avaliadas)."
        except Exception as e:
            _task_state["message"] = f"Erro: {e}"
        finally:
            _task_state["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse({"status": "started", "message": "Avaliação iniciada em segundo plano."})


@app.get("/acoes/status")
def task_status():
    return JSONResponse(_task_state)


@app.post("/empresas/adicionar")
def add_company_route(entrada: str = Form(...), nome: str = Form("")):
    try:
        con = db.connect()
        cid, ats, slug = companies.add(con, entrada.strip(), nome.strip() or None)
        return JSONResponse({"ok": True, "id": cid, "ats": ats, "slug": slug})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/curriculo/upload")
async def upload_resume_route(arquivo: UploadFile = File(...), reavaliar: bool = Form(True)):
    try:
        data = await arquivo.read()
        filename = arquivo.filename or "curriculo.pdf"
        prof = resume.save_uploaded_resume(filename, data)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    def _worker():
        _task_state["running"] = True
        try:
            _task_state["message"] = f"Currículo '{filename}' carregado! Recalculando aderência das vagas..."
            con = db.connect()
            con.execute("UPDATE jobs SET score=NULL, reason=NULL, missing=NULL, seniority_ok=NULL")
            con.commit()
            from . import matching
            matching.stage1(con, prof, resume.profile_query_text(prof))
            if reavaliar and llm.available():
                _task_state["message"] = "Avaliando as melhores vagas para o novo currículo com a IA..."
                matching.stage2(con, prof, limit=15)
            _task_state["message"] = "Pronto! Ranking atualizado para o novo currículo."
        except Exception as e:
            _task_state["message"] = f"Erro ao recalcular: {e}"
        finally:
            _task_state["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse({"ok": True, "message": "Currículo enviado! Atualizando vagas..."})


