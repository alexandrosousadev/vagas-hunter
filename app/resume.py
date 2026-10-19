"""Lê o currículo (PDF/DOCX) e gera um perfil estruturado com a IA (ou por heurística caso a IA esteja offline)."""
import io
import json
import re
import time

from . import llm
from .config import CFG, DATA, ROOT

CACHE = DATA / "perfil.json"

SYSTEM = (
    "Você é um recrutador especialista no mercado brasileiro (qualquer área: Tecnologia, Suporte, Dados, Design, Produto, Administrativo, Financeiro, RH, Marketing, Vendas, Engenharia, Saúde, etc.). "
    "Leia o currículo e responda só JSON no formato: "
    '{"resumo": str, "cargos": [str], "cargos_semelhantes": [str], "skills": [str], '
    '"senioridade": "estagio|junior|pleno|senior", "anos_experiencia": number}. '
    '"cargos" são os cargos que a pessoa ocupa ou busca; "cargos_semelhantes" são títulos de vaga '
    "parecidos para os quais ela também seria uma boa candidata (em português e inglês); "
    '"skills" são as principais ferramentas, competências técnicas e conhecimentos da área dela.'
)

KNOWN_SKILLS = [
    # Tech & Dados
    "Java", "Spring Boot", "PHP", "Laravel", "Python", "JavaScript", "TypeScript", "Node.js",
    "React", "React Native", "Angular", "Vue.js", "HTML", "CSS", "C#", ".NET", "Go", "SQL",
    "MySQL", "PostgreSQL", "MongoDB", "Docker", "AWS", "Azure", "Git", "Linux", "APIs REST",
    "Power BI", "Tableau", "Excel", "Pandas", "ETL", "Data Science", "Machine Learning",
    # Suporte, Infra & QA
    "Suporte Técnico", "Help Desk", "Service Desk", "ITIL", "Zendesk", "Jira", "Redes",
    "Windows", "Active Directory", "QA", "Testes Automatizados", "Selenium", "Cypress",
    # Produto, Design, Negócios, Mkt, RH, Finanças
    "Scrum", "Kanban", "Agile", "Figma", "UI/UX", "Product Discovery", "CRM", "Salesforce",
    "HubSpot", "RD Station", "Google Ads", "Meta Ads", "SEO", "Copywriting", "Inbound",
    "Vendas B2B", "SDR", "BDR", "Customer Success", "Atendimento ao Cliente", "SAP", "TOTVS",
    "Recrutamento e Seleção", "Departamento Pessoal", "Contabilidade", "Fluxo de Caixa", "Inglês",
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
    if "senior" in low or "sênior" in low or "especialista" in low:
        level = "senior"
    elif "pleno" in low or "mid-level" in low:
        level = "pleno"
    elif "estagi" in low or "intern" in low:
        level = "estagio"
    else:
        level = "junior"

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first_line = lines[0] if lines else "Candidato"
    # Tenta capturar cargos das primeiras linhas do currículo
    role_candidates = []
    for ln in lines[1:12]:
        if 4 <= len(ln) <= 65 and not any(x in ln.lower() for x in ("@", "http", "telefone", "phone", "idade", "cidade", "cpf")):
            if any(w in ln.lower() for w in ("analista", "desenvolvedor", "developer", "engineer", "engenheiro", "assistente", "auxiliar", "especialista", "consultor", "designer", "suporte", "gestor", "coordenador", "vendedor", "sdr", "bdr", "qa", "dados", "data", "produto", "product", "marketing", "financeiro", "rh", "recrutador", "atendimento", "técnico", "tecnico")):
                role_candidates.append(ln.split("|")[0].split("—")[0].strip())
    if not role_candidates:
        role_candidates = ["Analista", "Assistente"]

    return {
        "resumo": f"Perfil extraído automaticamente do currículo de {first_line} ({len(found_skills)} competências identificadas).",
        "cargos": role_candidates[:4],
        "cargos_semelhantes": role_candidates[:4],
        "skills": found_skills or ["Comunicação", "Trabalho em Equipe", "Resolução de Problemas"],
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
