"""Lê o currículo (PDF/DOCX) e gera um perfil estruturado com o Ollama (com cache)."""
import json

from . import llm
from .config import CFG, DATA, ROOT

CACHE = DATA / "perfil.json"

SYSTEM = (
    "Você é um recrutador técnico brasileiro. Leia o currículo e responda só JSON no formato: "
    '{"resumo": str, "cargos": [str], "cargos_semelhantes": [str], "skills": [str], '
    '"senioridade": "estagio|junior|pleno|senior", "anos_experiencia": number}. '
    '"cargos" são os cargos que a pessoa ocupa ou busca; "cargos_semelhantes" são títulos de vaga '
    "parecidos para os quais ela também seria uma boa candidata (em português e inglês)."
)


def resume_path():
    return ROOT / CFG.get("curriculo", "curriculo/curriculo.pdf")


def read_text() -> str:
    path = resume_path()
    if path.suffix.lower() == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    if path.suffix.lower() == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    return path.read_text(encoding="utf-8")


def _merge(profile: dict) -> dict:
    extra = CFG.get("perfil_extra") or {}
    for key in ("cargos", "skills"):
        profile[key] = list(dict.fromkeys((profile.get(key) or []) + (extra.get(key) or [])))
    if extra.get("senioridade"):
        profile["senioridade"] = extra["senioridade"]
    return profile


def get_profile(refresh=False) -> dict:
    path = resume_path()
    if not path.exists():
        if CACHE.exists():
            return _merge(json.loads(CACHE.read_text(encoding="utf-8")))
        return _merge({"resumo": "", "cargos": [], "cargos_semelhantes": [], "skills": [], "senioridade": "junior"})
    mtime = path.stat().st_mtime
    if not refresh and CACHE.exists():
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if cached.get("_mtime") == mtime or not refresh:
            return _merge(cached)
    text = read_text()
    profile = llm.chat_json(SYSTEM, text)
    profile["_mtime"] = mtime
    profile["_texto"] = text
    CACHE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return _merge(profile)


def profile_query_text(p: dict) -> str:
    """Texto usado no embedding do candidato."""
    return (
        f"Cargos: {', '.join(p.get('cargos', []) + p.get('cargos_semelhantes', []))}\n"
        f"Skills: {', '.join(p.get('skills', []))}\n"
        f"Senioridade: {p.get('senioridade', '')}\n{p.get('resumo', '')}"
    )
