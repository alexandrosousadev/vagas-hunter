"""Lê o currículo (PDF/DOCX) e gera um perfil estruturado com a IA (ou por heurística caso a IA esteja offline)."""
import io
import json
import re
import time

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

KNOWN_SKILLS = [
    "Java", "Spring Boot", "PHP", "Laravel", "Python", "Django", "FastAPI", "Flask",
    "JavaScript", "TypeScript", "Node.js", "NestJS", "React", "React Native", "Next.js",
    "Angular", "Vue.js", "HTML", "CSS", "Tailwind", "C#", ".NET", "Go", "Ruby", "Kotlin",
    "Swift", "Flutter", "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Oracle",
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Git", "Linux", "CI/CD", "GraphQL",
    "APIs REST", "Scrum", "JUnit", "Pytest", "Selenium", "Playwright",
]


def resume_path():
    return ROOT / CFG.get("curriculo", "curriculo/curriculo.pdf")


def extract_text_from_bytes(filename: str, data: bytes) -> str:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    return data.decode("utf-8", errors="ignore")


def read_text() -> str:
    path = resume_path()
    return extract_text_from_bytes(path.name, path.read_bytes())


def _fallback_profile(text: str) -> dict:
    """Extrai perfil por palavras-chave caso a IA não esteja configurada no servidor."""
    low = text.lower()
    found_skills = [s for s in KNOWN_SKILLS if re.search(rf"(?<![a-z0-9]){re.escape(s.lower())}(?![a-z0-9])", low)]
    if "senior" in low or "sênior" in low:
        level = "senior"
    elif "pleno" in low or "mid-level" in low:
        level = "pleno"
    elif "estagi" in low or "intern" in low:
        level = "estagio"
    else:
        level = "junior"

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first_line = lines[0] if lines else "Candidato"
    return {
        "resumo": f"Perfil extraído automaticamente do currículo de {first_line} ({len(found_skills)} skills identificadas).",
        "cargos": ["Desenvolvedor Full Stack", "Desenvolvedor Backend", "Desenvolvedor Frontend", "Software Developer"],
        "cargos_semelhantes": ["Full Stack Developer", "Software Engineer", "Backend Developer", "Frontend Developer"],
        "skills": found_skills or ["Java", "PHP", "JavaScript", "React", "Angular", "SQL", "Git"],
        "senioridade": level,
        "anos_experiencia": 1,
    }


def _merge(profile: dict) -> dict:
    if profile.get("_custom_upload"):
        return profile
    extra = CFG.get("perfil_extra") or {}
    for key in ("cargos", "skills"):
        profile[key] = list(dict.fromkeys((profile.get(key) or []) + (extra.get(key) or [])))
    if extra.get("senioridade"):
        profile["senioridade"] = extra["senioridade"]
    return profile


def save_uploaded_resume(filename: str, data: bytes) -> dict:
    """Salva o currículo enviado pelo navegador, extrai o perfil (com IA ou fallback) e atualiza o cache."""
    text = extract_text_from_bytes(filename, data)
    if not text or len(text.strip()) < 20:
        raise ValueError("Não foi possível extrair texto desse arquivo. Envie um PDF ou DOCX válido.")

    dest_dir = ROOT / "curriculo"
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = ".docx" if filename.lower().endswith(".docx") else ".pdf"
    dest_file = dest_dir / f"curriculo{ext}"
    dest_file.write_bytes(data)

    if llm.available():
        try:
            profile = llm.chat_json(SYSTEM, text)
        except Exception:
            profile = _fallback_profile(text)
    else:
        profile = _fallback_profile(text)

    profile["_mtime"] = time.time()
    profile["_texto"] = text
    profile["_custom_upload"] = True
    profile["_filename"] = filename
    CACHE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def get_profile(refresh=False) -> dict:
    if not refresh and CACHE.exists():
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if cached.get("_custom_upload"):
            return cached
        path = resume_path()
        if not path.exists() or cached.get("_mtime") == path.stat().st_mtime:
            return _merge(cached)

    path = resume_path()
    if not path.exists():
        if CACHE.exists():
            return _merge(json.loads(CACHE.read_text(encoding="utf-8")))
        return _merge({"resumo": "", "cargos": [], "cargos_semelhantes": [], "skills": [], "senioridade": "junior"})

    mtime = path.stat().st_mtime
    text = read_text()
    if llm.available():
        profile = llm.chat_json(SYSTEM, text)
    else:
        profile = _fallback_profile(text)
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
