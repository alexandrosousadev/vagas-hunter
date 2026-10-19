import hashlib
import sqlite3
from datetime import datetime, timezone

from .config import DATA

DB_PATH = DATA / "vagas.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ats TEXT NOT NULL,            -- greenhouse | lever | ashby | workable | inhire | generic
    slug TEXT NOT NULL,           -- slug no ATS, ou URL da página (generic)
    careers_url TEXT,
    active INTEGER DEFAULT 1,
    last_fetched TEXT,
    last_error TEXT,
    UNIQUE(ats, slug)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,          -- sha1(url)
    company_id INTEGER REFERENCES companies(id),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    location TEXT,
    description TEXT,
    posted_at TEXT,
    first_seen TEXT,
    last_seen TEXT,
    open INTEGER DEFAULT 1,       -- 0 quando a vaga sumiu do site
    embedding TEXT,               -- JSON
    stage1 REAL,                  -- nota da etapa 1 (0..1)
    score INTEGER,                -- nota da IA (0..100)
    reason TEXT,
    missing TEXT,
    seniority_ok INTEGER,
    scored_at TEXT,
    status TEXT DEFAULT 'nova'    -- nova | interessa | candidatei | descartada
);
CREATE INDEX IF NOT EXISTS ix_jobs_score ON jobs(score);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_id(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_company(con, name, ats, slug, careers_url=None) -> int:
    con.execute(
        "INSERT INTO companies(name, ats, slug, careers_url) VALUES (?,?,?,?) "
        "ON CONFLICT(ats, slug) DO UPDATE SET name=excluded.name, "
        "careers_url=COALESCE(excluded.careers_url, companies.careers_url), active=1",
        (name, ats, slug, careers_url),
    )
    con.commit()
    return con.execute("SELECT id FROM companies WHERE ats=? AND slug=?", (ats, slug)).fetchone()[0]


import re
import unicodedata


def dedup_key(title: str, company_name: str = "") -> str:
    """Gera uma chave normalizada de (título + empresa) para evitar a mesma vaga repetida em vários canais
    (ex: a mesma vaga da Rotha IA ou Coodesh postada em backend-br, frontendbr e react-brasil)."""
    s = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    # Remove tags iniciais como [Remoto], [Job-32297], (React), etc.
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\((?:react|angular|java|php|python|remoto|remote|brasil|brazil|pleno|junior|jr)\)", " ", s)
    s = re.sub(r"\b(remoto|remote|home office|brazil|brasil|na|no|em|at|vaga|de|da|do)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    clean_title = " ".join(s.split())

    comp = unicodedata.normalize("NFKD", company_name or "").encode("ascii", "ignore").decode().lower()
    # Se for agregador (GitHub, LinkedIn, Programathor, etc.), a empresa real já está no próprio título
    if any(ag in comp for ag in ("github", "linkedin", "programathor", "eu.dev", "posts")):
        return clean_title
    clean_comp = re.sub(r"[^a-z0-9]+", " ", comp).strip()
    if clean_comp and clean_comp not in clean_title:
        return f"{clean_comp}::{clean_title}"
    return clean_title


def deduplicate_open_jobs(con) -> int:
    """Marca como open=0 vagas abertas duplicadas entre canais (mantendo a que já tem nota/status ou a mais antiga)."""
    rows = con.execute("""
        SELECT j.id, j.title, j.score, j.status, j.first_seen, c.name AS company_name
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.open = 1
        ORDER BY
            CASE WHEN j.status IN ('candidatei', 'interessa') THEN 0 ELSE 1 END,
            CASE WHEN j.score IS NOT NULL THEN 0 ELSE 1 END,
            COALESCE(j.score, 0) DESC,
            j.first_seen ASC
    """).fetchall()
    seen_keys: set[str] = set()
    to_close: list[str] = []
    for r in rows:
        k = dedup_key(r["title"], r["company_name"])
        if not k:
            continue
        if k in seen_keys:
            to_close.append(r["id"])
        else:
            seen_keys.add(k)
    if to_close:
        marks = ",".join("?" * len(to_close))
        con.execute(f"UPDATE jobs SET open=0 WHERE id IN ({marks})", to_close)
        con.commit()
    return len(to_close)


def save_jobs(con, company_id: int, jobs: list) -> int:
    """Insere vagas novas, atualiza last_seen das existentes e marca como fechadas as que sumiram.
    Retorna quantas vagas são novas."""
    ts = now()
    new = 0
    seen = []
    for j in jobs:
        jid = job_id(j.url)
        seen.append(jid)
        cur = con.execute("UPDATE jobs SET last_seen=?, open=1, location=? WHERE id=?", (ts, j.location, jid))
        if cur.rowcount == 0:
            con.execute(
                "INSERT INTO jobs(id, company_id, title, url, location, description, posted_at, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (jid, company_id, j.title, j.url, j.location, j.description, j.posted_at, ts, ts),
            )
            new += 1
    if seen:
        marks = ",".join("?" * len(seen))
        con.execute(f"UPDATE jobs SET open=0 WHERE company_id=? AND id NOT IN ({marks})", (company_id, *seen))
    else:
        con.execute("UPDATE jobs SET open=0 WHERE company_id=?", (company_id,))
    con.execute("UPDATE companies SET last_fetched=?, last_error=NULL WHERE id=?", (ts, company_id))
    con.commit()
    deduplicate_open_jobs(con)
    return new

