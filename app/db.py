import hashlib
import hmac
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from .config import DATA

DB_PATH = DATA / "vagas.db"
SECRET = os.getenv("APP_SECRET", "vagas-hunter-secret-key-2026")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    profile_json TEXT,
    created_at TEXT
);
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
CREATE TABLE IF NOT EXISTS user_jobs (
    user_id INTEGER REFERENCES users(id),
    job_id TEXT REFERENCES jobs(id),
    stage1 REAL,
    score INTEGER,
    reason TEXT,
    missing TEXT,
    seniority_ok INTEGER,
    scored_at TEXT,
    status TEXT DEFAULT 'nova',
    PRIMARY KEY (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS ix_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS ix_user_jobs_user ON user_jobs(user_id, score);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_id(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), SECRET.encode(), 100_000).hex()


def verify_password(password: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), stored_hash)


def make_session_token(user_id: int, username: str) -> str:
    payload = f"{user_id}:{username}"
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}:{sig}"


def parse_session_token(token: str | None) -> tuple[int, str] | None:
    if not token or token.count(":") != 2:
        return None
    uid_str, username, sig = token.split(":", 2)
    if not uid_str.isdigit():
        return None
    expected = hmac.new(SECRET.encode(), f"{uid_str}:{username}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    return int(uid_str), username


def _ensure_default_user(con: sqlite3.Connection):
    """Garante que a conta principal (id=1) exista e tenha as notas/status iniciais migrados."""
    env_pw = os.getenv("DEFAULT_ADMIN_PASSWORD", "").strip()
    env_user = os.getenv("DEFAULT_ADMIN_USER", "alexandro").strip().lower()
    row = con.execute("SELECT id FROM users WHERE id=1").fetchone()
    if not row:
        # Hash PBKDF2 inicial caso DEFAULT_ADMIN_PASSWORD não esteja definida no ambiente
        pw_hash = hash_password(env_pw) if env_pw else "7dc5ef7bc2c79d69013fb364042ca806f565a1a6fe3f957a29970a1b179d9562"
        prof_path = DATA / "perfil.json"
        prof_txt = prof_path.read_text(encoding="utf-8") if prof_path.exists() else None
        con.execute(
            "INSERT INTO users(id, username, password_hash, profile_json, created_at) VALUES (1, ?, ?, ?, ?)",
            (env_user, pw_hash, prof_txt, now()),
        )
        con.execute("""
            INSERT OR IGNORE INTO user_jobs(user_id, job_id, stage1, score, reason, missing, seniority_ok, scored_at, status)
            SELECT 1, id, stage1, score, reason, missing, seniority_ok, scored_at, COALESCE(status, 'nova')
            FROM jobs
            WHERE stage1 IS NOT NULL OR score IS NOT NULL OR status != 'nova'
        """)
        con.commit()
    elif env_pw:
        con.execute(
            "UPDATE users SET username=?, password_hash=? WHERE id=1",
            (env_user, hash_password(env_pw)),
        )
        con.commit()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _ensure_default_user(con)
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


def dedup_key(title: str, company_name: str = "") -> str:
    """Gera uma chave normalizada de (título + empresa) para evitar a mesma vaga repetida em vários canais."""
    s = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\((?:react|angular|java|php|python|remoto|remote|brasil|brazil|pleno|junior|jr)\)", " ", s)
    s = re.sub(r"\b(remoto|remote|home office|brazil|brasil|na|no|em|at|vaga|de|da|do)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    clean_title = " ".join(s.split())

    comp = unicodedata.normalize("NFKD", company_name or "").encode("ascii", "ignore").decode().lower()
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
    """Insere vagas novas, atualiza last_seen das existentes e marca como fechadas as que sumiram."""
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
