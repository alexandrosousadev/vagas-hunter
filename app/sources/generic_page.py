"""Página de carreiras própria (sem ATS conhecido): extrai vagas diretamente do HTML/JSON-LD
(funciona no Render sem depender de Ollama) e usa o LLM como complemento quando disponível."""
import json
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .. import llm
from .base import Job, client, html_to_text

SYSTEM = (
    "Você extrai vagas de emprego de páginas de carreiras. Responda só JSON no formato "
    '{"vagas": [{"titulo": str, "url": str, "local": str}]}. '
    "Use apenas links que aparecem na lista de links fornecida. Se não houver vagas, devolva {\"vagas\": []}."
)

ROLE_TITLE_RE = re.compile(
    r"\b(desenvolvedor|desenvolvedora|developer|software engineer|engenheiro de software|engenheira de software|"
    r"programador|programadora|full[- ]?stack|back[- ]?end|front[- ]?end|analista de sistemas|"
    r"analista desenvolvedor|php|java|react|angular|node\.?js|\.net|python|mobile|est[aá]gio|trainee|j[uú]nior)\b",
    re.I,
)
SKIP_LINK_TEXT_RE = re.compile(
    r"^(saiba mais|ver mais|leia mais|apply|apply now|candidatar|candidate-se|ver vaga|detalhes|"
    r"sobre|contato|login|entrar|home|in[ií]cio|carreiras|careers|vagas|blog|pol[ií]tica|privacidade|termos)$",
    re.I,
)


def _heuristic_extract(url: str, page: str) -> list[Job]:
    """Extrai vagas de qualquer página de carreiras usando JSON-LD (JobPosting), cards ou links."""
    tree = HTMLParser(page)
    jobs: list[Job] = []
    seen: set[str] = set()

    # 1) Schema.org JobPosting em <script type="application/ld+json">
    for sc in tree.css('script[type="application/ld+json"]'):
        try:
            raw = json.loads(sc.text() or "")
            items = raw if isinstance(list, type(raw)) else [raw]
            if isinstance(raw, dict) and "@graph" in raw:
                items = raw["@graph"]
            for it in items:
                if not isinstance(it, dict) or it.get("@type") != "JobPosting":
                    continue
                title = (it.get("title") or "").strip()
                jurl = urljoin(url, it.get("url") or url)
                if not title or jurl in seen:
                    continue
                seen.add(jurl)
                desc = html_to_text(it.get("description") or "")
                loc_Type = str(it.get("jobLocationType") or "")
                remote = "TELECOMMUTE" in loc_Type.upper() or "remoto" in desc.lower() or "remote" in desc.lower()
                jobs.append(Job(
                    title=title,
                    url=jurl,
                    location="Brasil | Remoto" if remote else "Brasil",
                    description=desc[:4000],
                    remote=remote,
                ))
        except Exception:
            pass

    # 2) Links e elementos de vagas no HTML
    for a in tree.css("a[href]"):
        href_raw = (a.attributes.get("href") or "").strip()
        if not href_raw or href_raw.startswith(("javascript:", "mailto:", "tel:")):
            continue
        text = re.sub(r"\s+", " ", a.text(strip=True)).strip()
        parent = a.parent
        parent_txt = re.sub(r"\s+", " ", parent.text(separator=" ", strip=True)) if parent else text

        # Caso em que o botão diz "Apply Now / Candidate-se" e o título está no card pai
        if SKIP_LINK_TEXT_RE.match(text):
            if parent:
                heading = parent.css_first("h1, h2, h3, h4, .role-title, .job-title, strong")
                if heading:
                    text = re.sub(r"\s+", " ", heading.text(strip=True)).strip()

        if not text or len(text) < 6 or len(text) > 130 or SKIP_LINK_TEXT_RE.match(text):
            continue
        if not ROLE_TITLE_RE.search(text):
            continue

        full_url = urljoin(url, href_raw)
        key = f"{full_url}::{text.lower()}"
        if key in seen:
            continue
        seen.add(key)

        low = f"{text} {parent_txt}".lower()
        remote = any(w in low for w in ("remoto", "remote", "home office", "teletrabalho", "anywhere"))
        if any(w in low for w in ("presencial", "híbrido", "hibrido", "hybrid", "on-site")):
            if "100% remoto" not in low and "fully remote" not in low:
                remote = False

        jobs.append(
            Job(
                title=text,
                url=full_url,
                location="Brasil | Remoto" if remote else "Brasil",
                description=parent_txt[:3000],
                remote=remote,
            )
        )
    return jobs


def fetch(url: str) -> list[Job]:
    with client() as c:
        r = c.get(url)
        r.raise_for_status()
        page = r.text

    # Tenta primeiro extração determinística do HTML/JSON-LD (funciona sem Ollama no Render)
    jobs = _heuristic_extract(url, page)
    if jobs:
        return jobs

    if not llm.available():
        return []

    tree = HTMLParser(page)
    links = []
    for a in tree.css("a[href]"):
        text = a.text(strip=True)
        if text and len(text) < 150:
            links.append(f"- {text} -> {urljoin(url, a.attributes['href'])}")
    text = html_to_text(page)[:6000]
    user = f"URL: {url}\n\nTEXTO DA PÁGINA:\n{text}\n\nLINKS:\n" + "\n".join(links[:300])
    data = llm.chat_json(SYSTEM, user)
    valid = {urljoin(url, a.attributes["href"]) for a in tree.css("a[href]")}
    return [
        Job(title=v["titulo"], url=v["url"], location=v.get("local", ""))
        for v in data.get("vagas", [])
        if v.get("titulo") and v.get("url") in valid
    ]


def fetch_description(url: str) -> str:
    with client() as c:
        r = c.get(url)
        r.raise_for_status()
        return html_to_text(r.text)[:8000]
