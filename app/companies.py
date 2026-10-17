"""Cadastro de empresas: importa a lista inicial e detecta o ATS a partir de URL ou nome."""
import re
from pathlib import Path
from urllib.parse import urlparse

from . import db
from .config import CFG
from .sources import ATS
from .sources.base import client

SEED = Path(__file__).with_name("seed_companies.txt")

# padrões que revelam o ATS (na URL ou dentro do HTML da página de carreiras)
PATTERNS = [
    ("greenhouse", r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)"),
    ("lever", r"jobs\.lever\.co/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)"),
    ("workable", r"apply\.workable\.com/([\w-]+)"),
    ("inhire", r"([\w-]+)\.inhire\.app"),
]
IGNORE_SLUGS = {"embed", "api", "www", "j", "v1", "app"}


def _match(text: str):
    for ats, pat in PATTERNS:
        for m in re.finditer(pat, text, re.I):
            slug = m.group(1).lower()
            if slug not in IGNORE_SLUGS:
                return ats, slug
    return None


def _name_from_url(url: str) -> str:
    host = urlparse(url).hostname or url
    parts = [p for p in host.split(".") if p not in ("www", "careers", "carreiras", "jobs", "vagas", "trabalhe", "com", "br", "io")]
    return (parts[0] if parts else host).capitalize()


def detect(entry: str) -> tuple[str, str, str | None]:
    """Recebe 'ats:slug', uma URL de carreiras ou um nome. Devolve (ats, slug, careers_url)."""
    entry = entry.strip()
    if ":" in entry and not entry.startswith("http"):
        ats, slug = entry.split(":", 1)
        return ats.strip(), slug.strip(), None
    if entry.startswith("http"):
        if hit := _match(entry):
            return hit[0], hit[1], entry
        with client() as c:
            html = c.get(entry).text
        if hit := _match(html):
            return hit[0], hit[1], entry
        return "generic", entry, entry
    # nome solto: tenta o slug em cada ATS e fica com o que tiver mais vagas
    slug = re.sub(r"[^a-z0-9-]", "", entry.lower().replace(" ", ""))
    best = max(((ats, mod.probe(slug)) for ats, mod in ATS.items()), key=lambda x: x[1])
    if best[1] == 0:
        raise ValueError(f"Nenhum ATS conhecido tem vagas para '{entry}'. Tente a URL da página de carreiras.")
    return best[0], slug, None


def add(con, entry: str, name: str | None = None) -> tuple[int, str, str]:
    ats, slug, url = detect(entry)
    name = name or (_name_from_url(url) if url else slug.capitalize())
    cid = db.upsert_company(con, name, ats, slug, url)
    return cid, ats, slug


def import_all(con, verbose=True) -> int:
    n = 0
    for line in SEED.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, name = line.partition(" ")
        ats, slug = key.split(":", 1)
        db.upsert_company(con, name.strip() or slug, ats, slug)
        n += 1
    for entry in CFG.get("empresas") or []:
        try:
            _, ats, slug = add(con, entry)
            n += 1
            if verbose:
                print(f"  + {entry} -> {ats}:{slug}")
        except Exception as e:
            print(f"  ! {entry}: {e}")
    return n
