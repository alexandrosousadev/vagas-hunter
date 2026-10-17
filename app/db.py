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
    return new
