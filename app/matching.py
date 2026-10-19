"""Filtros e as duas etapas de matching.

Etapa 1 (rápida, roda em todas as vagas): similaridade de embeddings + bônus por skills/cargos.
Etapa 2 (lenta, só top N): o modelo de chat dá nota de 0 a 100 com justificativa.
"""
import json
import math
import re
import unicodedata

from . import db, llm
from .config import CFG
from .sources import generic_page

REMOTE_WORDS = ["remote", "remoto", "remota", "home office", "anywhere", "100% remoto", "teletrabalho"]
NON_REMOTE_WORDS = ["hybrid", "hibrido", "presencial", "on-site", "onsite", "in-office"]
BR_PLACES = ["br", "sao paulo", "rio de janeiro", "belo horizonte", "curitiba", "florianopolis", "porto alegre",
             "recife", "fortaleza", "salvador", "campinas", "brasilia", "goiania"]
FOREIGN = ["united states", "usa", "us", "u s", "canada", "mexico", "colombia", "co", "argentina", "ar", "chile",
           "cl", "peru", "uruguay", "uy", "europe", "emea", "apac", "uk", "united kingdom", "germany", "spain",
           "portugal", "pt", "france", "india", "ireland", "netherlands", "poland", "new york", "london",
           "barcelona", "lisbon", "ciudad de mexico", "bogota", "buenos aires", "santiago", "manhattan"]
# frases na descrição que indicam vaga remota quando o campo de local não diz
DESC_REMOTE = ["100% remot", "totalmente remot", "trabalho remoto", "modelo remoto", "modalidade remota",
               "fully remote", "remote-first", "remote first", "home office", "work from anywhere"]
DESC_NOT_REMOTE = ["hibrid", "hybrid", "presencial", "on-site", "dias no escritorio", "days in the office"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower())


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(_norm(word))}(?![a-z0-9])", text) is not None


# ---------- filtros ----------

ALWAYS_EXCLUDE_SUBSTRINGS = (
    "pessoa com deficiencia",
    "pessoas com deficiencia",
    "people with disabilities",
    "vaga afirmativa",
    "affirmative position",
    "exclusiva para pessoas",
    "exclusivo para pessoas",
    "banco de talentos",
    "talent pool",
    "general interest",
    "cadastre-se aqui",
    "plenonova",
    "seniornova",
    "javasr",
)

DEV_REQUIRED_WORDS = (
    "desenvolvedor",
    "desenvolvedora",
    "desenvolvimento",
    "developer",
    "development",
    "dev",
    "software",
    "engineer",
    "engenheiro",
    "engenheira",
    "engenharia",
    "programador",
    "programadora",
    "fullstack",
    "full stack",
    "backend",
    "back end",
    "frontend",
    "front end",
    "java",
    "php",
    "laravel",
    "spring",
    "angular",
    "react",
    "node",
    "javascript",
    "typescript",
    "python",
    "dotnet",
    "mobile",
    "android",
    "flutter",
    "web",
)

NON_DEV_EXCLUDE_WORDS = (
    "pesquisa",
    "ouvidoria",
    "atendimento",
    "vendas",
    "pre vendas",
    "bdr",
    "sdr",
    "sales",
    "account executive",
    "customer success",
    "customer sucess",
    "marketing",
    "copywriter",
    "writer",
    "interpreter",
    "linguist",
    "recruiter",
    "talent acquisition",
    "people analytics",
    "enfermagem",
    "enfermeiro",
    "enfermeira",
    "contabil",
    "controladoria",
    "juridic",
    "legal",
    "financeiro",
    "fp a",
    "facilities",
    "backoffice",
    "back office",
    "cobranca",
    "despejo",
    "animador",
    "animadora",
    "designer",
    "instructional",
    "hypercare",
    "alliances",
    "change management",
    "client partner",
    "office assistant",
    "suporte n2",
    "technical support",
    "support engineer",
    "consultor de suporte",
    "contact center",
    "zendesk",
    "servicenow",
    "cobol",
    "abap",
    "sap",
    "rpa",
    "power automate",
    "go to market",
    "business operations",
    "gestao estrategica",
    "administrative",
    "administrativo",
    "treinamento de ia",
    "avaliador de qualidade",
    "avaliacao de qualidade",
    "pesquisa clinica",
    "administracao de banco de dados",
    "security engineer",
    "cybersecurity",
    "cloudsec",
    "appsec",
    "sre",
    "devops",
)


def title_ok(title: str, description: str = "") -> bool:
    t = _norm(title).replace(".", " ").replace("-", " ")
    if any(sub in t for sub in ALWAYS_EXCLUDE_SUBSTRINGS):
        return False
    extra_words = ["pcd", "specialist", "especialista", "intermediate", "middle", "pleno", "mid"]
    for w in list(CFG.get("excluir_titulos", [])) + extra_words:
        if _has_word(t, w.replace(".", "").replace("-", " ")):
            return False
    if description:
        d = _norm(description[:1500])
        if any(
            p in d
            for p in (
                "exclusiva para pessoas com deficiencia",
                "vaga exclusiva para pcd",
                "exclusiva pcd",
                "affirmative position for people with disabilities",
            )
        ):
            return False
    return True


def career_match_ok(title: str, profile: dict | None = None) -> bool:
    """Garante que o título da vaga pertence à área profissional do currículo do usuário."""
    if not title_ok(title):
        return False
    t = _norm(title).replace(".", " ").replace("-", " ")

    cargos_norm = " ".join(_norm(c) for c in (profile or {}).get("cargos", []))
    is_dev_profile = (not cargos_norm) or any(
        w in cargos_norm for w in ("desenvolvedor", "developer", "programador", "software", "full stack", "backend", "frontend")
    )

    if is_dev_profile:
        if any(_has_word(t, bad) for bad in NON_DEV_EXCLUDE_WORDS):
            return False
        return any(_has_word(t, req) for req in DEV_REQUIRED_WORDS)

    # Para currículos de outras áreas (RH, Finanças, Design, etc.), exige pelo menos 1 palavra dos cargos/skills
    role_words = {
        w
        for c in (profile or {}).get("cargos", []) + (profile or {}).get("cargos_semelhantes", []) + (profile or {}).get("skills", [])
        for w in _norm(c).replace("-", " ").split()
        if len(w) >= 3 and w not in ("para", "com", "dos", "das", "pleno", "junior", "senior", "analista", "assistente", "auxiliar")
    }
    if not role_words:
        return True
    return any(_has_word(t, rw) for rw in role_words)


def location_ok(location: str, remote_flag: bool | None, description: str = "") -> bool:
    """Vaga remota que aceita gente do Brasil. As empresas cadastradas são brasileiras ou têm operação aqui,
    então "Remote" sem país é aceito; só rejeita quando o local aponta outro país."""
    cfg = CFG.get("filtro_local", {})
    loc = _norm(location)
    accept = [_norm(a) for a in cfg.get("aceitar", [])]
    br_terms = [a for a in accept if a not in map(_norm, REMOTE_WORDS)] + BR_PLACES
    in_brazil = any(_has_word(loc, t) for t in br_terms)
    foreign = any(_has_word(loc, t) for t in FOREIGN)
    if foreign and not in_brazil:
        return False
    if not cfg.get("exigir_remoto", True):
        return in_brazil or not loc
    if remote_flag or any(_has_word(loc, w) for w in REMOTE_WORDS):
        return True
    if any(_has_word(loc, w) for w in NON_REMOTE_WORDS):
        return False
    desc = _norm(description)
    return any(p in desc for p in DESC_REMOTE) and not any(p in desc for p in DESC_NOT_REMOTE)


# ---------- etapa 1 ----------

def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def stage1(con, profile: dict, query_text: str, user_id: int = 1) -> int:
    llm_ok = llm.available()
    qv = None
    if llm_ok:
        rows = con.execute(
            "SELECT id, title, description FROM jobs WHERE open=1 AND embedding IS NULL"
        ).fetchall()
        if rows:
            print(f"Etapa 1: gerando embeddings de {len(rows)} vagas...")
        for i in range(0, len(rows), 32):
            batch = rows[i:i + 32]
            vecs = llm.embed([f"{r['title']}\n{(r['description'] or '')[:3000]}" for r in batch])
            for r, v in zip(batch, vecs):
                con.execute("UPDATE jobs SET embedding=? WHERE id=?", (json.dumps(v), r["id"]))
            con.commit()
        try:
            qv = llm.embed([query_text], kind="query")[0]
        except Exception:
            qv = None

    skills = [_norm(s) for s in profile.get("skills", [])]
    titles = {w for c in profile.get("cargos", []) + profile.get("cargos_semelhantes", [])
              for w in _norm(c).split() if len(w) > 3}
    level_words = {
        "estagio": ["estagio", "estagiario", "intern", "internship"],
        "junior": ["jr", "junior", "trainee", "entry level", "associate"],
        "pleno": ["pleno", "pl", "mid", "mid level", "ii"],
        "senior": ["senior", "sr", "staff", "lead", "principal"],
    }.get(_norm(profile.get("senioridade", "")), [])
    n = 0
    for r in con.execute("SELECT id, title, description, embedding FROM jobs WHERE open=1").fetchall():
        if not title_ok(r["title"], r["description"] or "") or not career_match_ok(r["title"], profile):
            s1_val = 0.0
        else:
            text = _norm(f"{r['title']} {r['description'] or ''}")
            sim = 0.55
            if qv and r["embedding"]:
                try:
                    emb = json.loads(r["embedding"])
                    if len(emb) == len(qv):
                        sim = _cos(qv, emb)
                except Exception:
                    pass
            skill_hits = sum(1 for s in skills if _has_word(text, s)) / max(len(skills), 1)
            title = _norm(r["title"])
            title_hit = 0.08 if titles & set(title.split()) else 0
            level_hit = 0.07 if any(_has_word(title, w) for w in level_words) else 0
            s1_val = round(sim + 0.25 * skill_hits + title_hit + level_hit, 4)
        con.execute(
            """
            INSERT INTO user_jobs (user_id, job_id, stage1)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, job_id) DO UPDATE SET stage1=excluded.stage1
            """,
            (user_id, r["id"], s1_val),
        )
        if user_id == 1:
            con.execute("UPDATE jobs SET stage1=? WHERE id=?", (s1_val, r["id"]))
        n += 1
    con.commit()
    return n


# ---------- etapa 2 ----------

SYSTEM = (
    "Você é um recrutador brasileiro avaliando se uma vaga combina com um candidato (qualquer área: TI, Suporte, Dados, Design, Produto, Administrativo, Financeiro, Comercial, RH, etc.). "
    "Analise com cuidado e responda só JSON com estes campos, nesta ordem:\n"
    '"skills_em_comum": [str]  -- competências/ferramentas exigidas pela vaga que o candidato tem\n'
    '"skills_faltando": [str]  -- só as obrigatórias/importantes que ele não tem (máx. 6)\n'
    '"aderencia_stack": 0-10   -- 10 = função e requisitos idênticos ao perfil; 7 = mesma área e maioria das competências em comum; 4 = área parecida, mas faltam competências-chave; 0 = outra profissão/área sem relação\n'
    '"nivel_vaga": "estagio|junior|pleno|senior|especialista"\n'
    '"exige_ingles_fluente": true|false\n'
    '"requisito_eliminatorio": true|false  -- algo que o candidato claramente não cumpre (ex.: outra profissão, formação/registro específico obrigatório, 5+ anos quando é júnior)\n'
    '"motivo": "1-2 frases em português explicando o encaixe"'
)
LEVELS = {"estagio": 0, "junior": 1, "pleno": 2, "senior": 3, "especialista": 4}


def compute_score(res: dict, candidate_level: str) -> tuple[int, bool]:
    """Nota final calculada a partir dos critérios (mais estável que pedir um número ao modelo)."""
    stack = max(0, min(10, float(res.get("aderencia_stack") or 0)))
    gap = LEVELS.get(_norm(res.get("nivel_vaga") or ""), 2) - LEVELS.get(_norm(candidate_level or ""), 1)
    score = stack * 10
    score -= 15 * max(gap, 0)                      # vaga acima do nível do candidato
    score -= 15 if res.get("exige_ingles_fluente") else 0
    score -= 30 if res.get("requisito_eliminatorio") else 0
    return int(max(0, min(100, round(score)))), gap <= 0


def stage2(con, profile: dict, limit: int | None = None, user_id: int = 1) -> int:
    cfg = CFG.get("matching", {})
    limit = limit or cfg.get("top_n_ia", 40)
    rows = con.execute(
        """
        SELECT j.*, c.name AS company, c.ats, COALESCE(uj.stage1, j.stage1, 0) AS u_stage1
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
        WHERE j.open = 1 AND uj.score IS NULL AND COALESCE(uj.stage1, j.stage1, 0) >= ?
        ORDER BY u_stage1 DESC
        LIMIT ?
        """,
        (user_id, cfg.get("similaridade_minima", 0.5), limit),
    ).fetchall()
    candidate = (
        f"Senioridade: {profile.get('senioridade')}\nCargos: {', '.join(profile.get('cargos', []))}\n"
        f"Skills: {', '.join(profile.get('skills', []))}\n\nCURRÍCULO:\n{profile.get('_texto', '')[:3500]}"
    )
    for i, r in enumerate(rows, 1):
        desc = r["description"] or ""
        if not desc and r["ats"] == "generic":
            try:
                desc = generic_page.fetch_description(r["url"])
                con.execute("UPDATE jobs SET description=? WHERE id=?", (desc, r["id"]))
            except Exception:
                pass
        job = f"VAGA: {r['title']}\nEmpresa: {r['company']}\nLocal: {r['location']}\n\n{desc[:5000]}"
        try:
            res = llm.chat_json(SYSTEM, f"CANDIDATO\n{candidate}\n\n---\n\n{job}")
            nota, level_ok = compute_score(res, profile.get("senioridade", "junior"))
        except Exception as e:
            print(f"  ! erro avaliando {r['title']}: {e}")
            continue
        missing = res.get("skills_faltando") or []
        reason_txt = f"[{res.get('nivel_vaga', '?')}] {res.get('motivo', '')}"
        missing_txt = ", ".join(map(str, missing[:6]))
        scored_at = db.now()
        con.execute(
            """
            INSERT INTO user_jobs (user_id, job_id, score, reason, missing, seniority_ok, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, job_id) DO UPDATE SET
                score=excluded.score,
                reason=excluded.reason,
                missing=excluded.missing,
                seniority_ok=excluded.seniority_ok,
                scored_at=excluded.scored_at
            """,
            (user_id, r["id"], nota, reason_txt, missing_txt, int(level_ok), scored_at),
        )
        if user_id == 1:
            con.execute(
                "UPDATE jobs SET score=?, reason=?, missing=?, seniority_ok=?, scored_at=? WHERE id=?",
                (nota, reason_txt, missing_txt, int(level_ok), scored_at, r["id"]),
            )
        con.commit()
        print(f"  [{i}/{len(rows)}] {nota:3d}  {r['company']} - {r['title']}")
    return len(rows)
