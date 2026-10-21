import time

from . import db, llm, matching, resume, sources
from .config import CFG


def collect(con, company: str | None = None) -> int:
    pause = CFG.get("coleta", {}).get("intervalo_segundos", 0.5)
    q = "SELECT * FROM companies WHERE active=1"
    args = ()
    if company:
        q += " AND (slug=? OR lower(name)=lower(?))"
        args = (company, company)
    total_new = 0
    try:
        profile = resume.get_profile(user_id=1, con=con) or None
    except Exception:
        profile = None
    for c in con.execute(q, args).fetchall():
        try:
            jobs = sources.fetch(c["ats"], c["slug"])
        except Exception as e:
            con.execute("UPDATE companies SET last_error=? WHERE id=?", (str(e)[:300], c["id"]))
            con.commit()
            print(f"  ! {c['name']:<25} erro: {str(e)[:80]}")
            continue
        kept = [
            j for j in jobs
            if matching.title_ok(j.title, j.description)
            and matching.career_match_ok(j.title, profile)
            and matching.location_ok(j.location, j.remote, j.description)
        ]
        new = db.save_jobs(con, c["id"], kept)
        total_new += new
        print(f"  {c['name']:<25} {len(jobs):4d} vagas, {len(kept):3d} remotas/compatíveis, {new:3d} novas")
        time.sleep(pause)
    return total_new


def run(company: str | None = None, use_ai: bool = True):
    con = db.connect()
    if not con.execute("SELECT 1 FROM companies LIMIT 1").fetchone():
        from . import companies
        print("Importando lista inicial de empresas...")
        companies.import_all(con)
    print("Coletando vagas...")
    new = collect(con, company)
    print(f"{new} vagas novas.")
    if not use_ai:
        return
    if not llm.available():
        print("Ollama não está rodando: pulei o matching. Abra o Ollama e rode `python run.py avaliar`.")
        return
    evaluate(con)


def evaluate(con=None, limit: int | None = None, user_id: int = 1):
    con = con or db.connect()
    profile = resume.get_profile(user_id=user_id, con=con)
    if not profile:
        return 0
    matching.stage1(con, profile, resume.profile_query_text(profile), user_id=user_id)
    print("Etapa 2: avaliando as melhores vagas com a IA local...")
    n = matching.stage2(con, profile, limit, user_id=user_id)
    print(f"{n} vagas avaliadas.")
    return n
