"""Painel web local (FastAPI + Jinja2 + HTMX)."""
import re
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from contextlib import asynccontextmanager
import time

from . import companies, db, llm, pipeline, resume
from .config import CFG

COOKIE_NAME = "vh_session"
_task_state = {"running": False, "message": "", "last_sync": ""}


def _current_user(request: Request) -> tuple[int, str] | None:
    token = request.cookies.get(COOKIE_NAME)
    return db.parse_session_token(token)


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
            pipeline.evaluate(con, limit=limit, user_id=1)
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


def _query_jobs(
    con,
    user_id: int = 1,
    q: str = "",
    status: str = "ativas",
    min_score: int = 0,
    company_id: int = 0,
    ats: str = "",
    only_scored: bool = False,
):
    sql = """
        SELECT
            j.id, j.company_id, j.title, j.url, j.location, j.description,
            j.posted_at, j.first_seen, j.last_seen, j.open,
            uj.stage1 AS stage1,
            uj.score AS score,
            uj.reason AS reason,
            uj.missing AS missing,
            uj.seniority_ok AS seniority_ok,
            uj.scored_at AS scored_at,
            COALESCE(uj.status, 'nova') AS status,
            c.name AS company_name, c.ats AS company_ats, c.slug AS company_slug
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
        WHERE j.open = 1
    """
    params: list = [user_id]

    if status == "ativas":
        sql += " AND COALESCE(uj.status, 'nova') IN ('nova', 'interessa')"
    elif status != "todas":
        sql += " AND COALESCE(uj.status, 'nova') = ?"
        params.append(status)

    if min_score > 0:
        sql += " AND COALESCE(uj.score, -1) >= ?"
        params.append(min_score)

    if only_scored:
        sql += " AND uj.score IS NOT NULL"

    if company_id > 0:
        sql += " AND j.company_id = ?"
        params.append(company_id)

    if ats == "ats_direto":
        sql += " AND c.ats IN ('greenhouse', 'lever', 'ashby', 'workable', 'inhire', 'generic')"
    elif ats:
        sql += " AND c.ats = ?"
        params.append(ats)

    if q.strip():
        term = f"%{q.strip()}%"
        sql += " AND (j.title LIKE ? OR c.name LIKE ? OR j.description LIKE ? OR COALESCE(uj.reason, '') LIKE ?)"
        params.extend([term, term, term, term])

    sql += """
        ORDER BY
            CASE WHEN uj.score IS NOT NULL THEN 0 ELSE 1 END,
            COALESCE(uj.score, 0) DESC,
            COALESCE(uj.stage1, 0) DESC,
            j.first_seen DESC
        LIMIT 250
    """
    return con.execute(sql, params).fetchall()


def _get_single_user_job(con, user_id: int, job_id: str):
    return con.execute(
        """
        SELECT
            j.id, j.company_id, j.title, j.url, j.location, j.description,
            j.posted_at, j.first_seen, j.last_seen, j.open,
            uj.stage1 AS stage1,
            uj.score AS score,
            uj.reason AS reason,
            uj.missing AS missing,
            uj.seniority_ok AS seniority_ok,
            uj.scored_at AS scored_at,
            COALESCE(uj.status, 'nova') AS status,
            c.name AS company_name, c.ats AS company_ats, c.slug AS company_slug
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
        WHERE j.id = ?
        """,
        (user_id, job_id),
    ).fetchone()


def _stats(con, user_id: int = 1):
    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN uj.score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
            SUM(CASE WHEN uj.score >= 70 AND COALESCE(uj.status, 'nova') != 'descartada' THEN 1 ELSE 0 END) AS high_match,
            SUM(CASE WHEN COALESCE(uj.status, 'nova') = 'nova' THEN 1 ELSE 0 END) AS novas,
            SUM(CASE WHEN COALESCE(uj.status, 'nova') = 'interessa' THEN 1 ELSE 0 END) AS interessa,
            SUM(CASE WHEN COALESCE(uj.status, 'nova') = 'candidatei' THEN 1 ELSE 0 END) AS candidatei,
            SUM(CASE WHEN COALESCE(uj.status, 'nova') = 'descartada' THEN 1 ELSE 0 END) AS descartadas
        FROM jobs j
        LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
        WHERE j.open = 1
    """, (user_id,)).fetchone()
    comp_count = con.execute("SELECT COUNT(*) FROM companies WHERE active = 1").fetchone()[0]
    return {**(dict(row) if row else {}), "companies": comp_count}


SOURCE_LABELS = {
    "linkedin": "LinkedIn (Remoto)",
    "posts": "Posts & E-mail RH",
    "eudev": "eu.dev.br (Júnior)",
    "vagascom": "Vagas.com.br (Home Office)",
    "programathor": "Programathor",
    "github": "GitHub Vagas BR",
    "jobicy": "Jobicy (Brasil/LATAM)",
    "remotive": "Remotive (Global/LATAM)",
    "greenhouse": "Greenhouse (Site Empresa)",
    "inhire": "InHire (Site Empresa)",
    "lever": "Lever (Site Empresa)",
    "ashby": "Ashby (Site Empresa)",
    "workable": "Workable (Site Empresa)",
}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, erro: str = Query("")):
    user = _current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    db.connect()
    return templates.TemplateResponse(request, "login.html", {"request": request, "erro": erro})


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    acao: str = Form("login"),
):
    uname = re.sub(r"[^a-z0-9_.-]", "", username.strip().lower())
    if len(uname) < 2:
        return templates.TemplateResponse(
            request, "login.html", {"request": request, "erro": "Informe um nome de usuário válido (mín. 2 letras)."}
        )
    if len(password) < 4:
        return templates.TemplateResponse(
            request, "login.html", {"request": request, "erro": "A senha deve ter pelo menos 4 caracteres."}
        )

    con = db.connect()
    row = con.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (uname,)).fetchone()

    if acao == "register":
        if row:
            return templates.TemplateResponse(
                request, "login.html", {"request": request, "erro": f"O usuário '{uname}' já existe. Faça login."}
            )
        cur = con.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            (uname, db.hash_password(password), db.now()),
        )
        con.commit()
        user_id = cur.lastrowid
    else:
        if not row or not db.verify_password(password, row["password_hash"]):
            return templates.TemplateResponse(
                request, "login.html", {"request": request, "erro": "Usuário ou senha incorretos."}
            )
        user_id = row["id"]

    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        db.make_session_token(user_id, uname),
        max_age=60 * 60 * 24 * 60,
        httponly=True,
        samesite="lax",
    )
    return resp


@app.post("/logout")
def logout_route():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.post("/conta/senha")
def change_password_route(request: Request, nova_senha: str = Form(...)):
    user = _current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autenticado"}, status_code=401)
    if len(nova_senha.strip()) < 4:
        return JSONResponse({"ok": False, "error": "A senha deve ter pelo menos 4 caracteres."}, status_code=400)
    con = db.connect()
    con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (db.hash_password(nova_senha.strip()), user[0]))
    con.commit()
    return JSONResponse({"ok": True, "message": "Senha alterada com sucesso!"})


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = Query(""),
    status: str = Query("ativas"),
    min_score: int = Query(0),
    company_id: int = Query(0),
    ats: str = Query(""),
    only_scored: bool = Query(False),
):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    user_id, username = user

    con = db.connect()
    jobs = _query_jobs(
        con, user_id=user_id, q=q, status=status, min_score=min_score, company_id=company_id, ats=ats, only_scored=only_scored
    )
    stats = _stats(con, user_id=user_id)
    comps = con.execute(
        "SELECT c.id, c.name, c.ats, COUNT(j.id) AS job_count "
        "FROM companies c LEFT JOIN jobs j ON j.company_id = c.id AND j.open = 1 "
        "WHERE c.active = 1 GROUP BY c.id ORDER BY c.name"
    ).fetchall()
    sources_rows = con.execute(
        "SELECT c.ats, COUNT(j.id) AS job_count "
        "FROM companies c JOIN jobs j ON j.company_id = c.id AND j.open = 1 "
        "WHERE c.active = 1 GROUP BY c.ats ORDER BY job_count DESC"
    ).fetchall()
    sources = [
        {"ats": r["ats"], "label": SOURCE_LABELS.get(r["ats"], r["ats"].upper()), "count": r["job_count"]}
        for r in sources_rows
    ]
    try:
        prof = resume.get_profile(user_id=user_id, con=con)
    except Exception:
        prof = {}

    ctx = {
        "request": request,
        "username": username,
        "user_id": user_id,
        "jobs": jobs,
        "stats": stats,
        "companies": comps,
        "sources": sources,
        "profile": prof,
        "ollama_ok": llm.available(),
        "task": _task_state,
        "filters": {
            "q": q,
            "status": status,
            "min_score": min_score,
            "company_id": company_id,
            "ats": ats,
            "only_scored": only_scored,
        },
    }
    if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "jobs-container":
        return templates.TemplateResponse(request, "_jobs_list.html", ctx)
    return templates.TemplateResponse(request, "index.html", ctx)


@app.post("/jobs/{job_id}/status", response_class=HTMLResponse)
def update_job_status(request: Request, job_id: str, status: str = Form(...)):
    user = _current_user(request)
    user_id = user[0] if user else 1
    allowed = {"nova", "interessa", "candidatei", "descartada"}
    if status not in allowed:
        return HTMLResponse("Status inválido", status_code=400)
    con = db.connect()
    con.execute(
        """
        INSERT INTO user_jobs(user_id, job_id, status)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, job_id) DO UPDATE SET status=excluded.status
        """,
        (user_id, job_id, status),
    )
    if user_id == 1:
        con.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    con.commit()
    job = _get_single_user_job(con, user_id, job_id)
    return templates.TemplateResponse(request, "_job_card.html", {"request": request, "j": job})


@app.post("/jobs/{job_id}/avaliar", response_class=HTMLResponse)
def evaluate_single_job(request: Request, job_id: str):
    user = _current_user(request)
    user_id = user[0] if user else 1
    con = db.connect()
    r = _get_single_user_job(con, user_id, job_id)
    if not r:
        return HTMLResponse("Vaga não encontrada", status_code=404)

    profile = resume.get_profile(user_id=user_id, con=con)
    if not profile:
        return HTMLResponse("Envie seu currículo primeiro para avaliar vagas.", status_code=400)
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
    reason_txt = f"[{res.get('nivel_vaga', '?')}] {res.get('motivo', '')}"
    missing_txt = ", ".join(map(str, missing[:6]))
    scored_at = db.now()
    con.execute(
        """
        INSERT INTO user_jobs(user_id, job_id, score, reason, missing, seniority_ok, scored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, job_id) DO UPDATE SET
            score=excluded.score,
            reason=excluded.reason,
            missing=excluded.missing,
            seniority_ok=excluded.seniority_ok,
            scored_at=excluded.scored_at
        """,
        (user_id, job_id, nota, reason_txt, missing_txt, int(level_ok), scored_at),
    )
    if user_id == 1:
        con.execute(
            "UPDATE jobs SET score=?, reason=?, missing=?, seniority_ok=?, scored_at=? WHERE id=?",
            (nota, reason_txt, missing_txt, int(level_ok), scored_at, job_id),
        )
    con.commit()
    job = _get_single_user_job(con, user_id, job_id)
    return templates.TemplateResponse(request, "_job_card.html", {"request": request, "j": job})


def matching_system() -> str:
    from . import matching
    return matching.SYSTEM


@app.post("/acoes/coletar")
def trigger_collect(request: Request, avaliar: bool = Form(True)):
    user = _current_user(request)
    user_id = user[0] if user else 1
    if _task_state["running"]:
        return JSONResponse({"status": "already_running", "message": _task_state["message"]})

    def _worker():
        _task_state["running"] = True
        try:
            _task_state["message"] = "Coletando vagas nas empresas..."
            con = db.connect()
            new = pipeline.collect(con)
            if avaliar and llm.available():
                _task_state["message"] = f"{new} vagas novas. Avaliando com a IA..."
                pipeline.evaluate(con, limit=15, user_id=user_id)
            _task_state["message"] = f"Concluído ({new} vagas novas)."
        except Exception as e:
            _task_state["message"] = f"Erro: {e}"
        finally:
            _task_state["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse({"status": "started", "message": "Coleta iniciada em segundo plano."})


@app.post("/acoes/avaliar")
def trigger_evaluate(request: Request, limite: int = Form(15)):
    user = _current_user(request)
    user_id = user[0] if user else 1
    if _task_state["running"]:
        return JSONResponse({"status": "already_running", "message": _task_state["message"]})

    def _worker():
        _task_state["running"] = True
        try:
            _task_state["message"] = f"Avaliando até {limite} vagas com a IA para o seu perfil..."
            con = db.connect()
            n = pipeline.evaluate(con, limit=limite, user_id=user_id)
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
async def upload_resume_route(
    request: Request,
    arquivo: UploadFile = File(...),
    reavaliar: bool = Form(True),
):
    user = _current_user(request)
    user_id = user[0] if user else 1
    try:
        data = await arquivo.read()
        filename = arquivo.filename or "curriculo.pdf"
        con = db.connect()
        prof = resume.save_uploaded_resume(filename, data, user_id=user_id, con=con)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    def _worker():
        _task_state["running"] = True
        try:
            _task_state["message"] = f"Currículo '{filename}' salvo na sua conta! Recalculando aderência..."
            wcon = db.connect()
            wcon.execute(
                "UPDATE user_jobs SET score=NULL, reason=NULL, missing=NULL, seniority_ok=NULL WHERE user_id=?",
                (user_id,),
            )
            wcon.commit()
            from . import matching
            matching.stage1(wcon, prof, resume.profile_query_text(prof), user_id=user_id)
            if reavaliar and llm.available():
                _task_state["message"] = "Avaliando as melhores vagas para o seu currículo com a IA..."
                matching.stage2(wcon, prof, limit=15, user_id=user_id)
            _task_state["message"] = "Pronto! Seu ranking exclusivo foi atualizado."
        except Exception as e:
            _task_state["message"] = f"Erro ao recalcular: {e}"
        finally:
            _task_state["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse({"ok": True, "message": "Currículo enviado! Atualizando suas vagas..."})



