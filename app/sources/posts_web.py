"""Busca vagas postadas em Posts/Feed do LinkedIn, Recrutei e páginas abertas com envio por e-mail
(usando busca web restrita à última semana e verificando se a vaga ainda está aberta)."""
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client, html_to_text

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
LI_JOB_ID_RE = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d{8,})")

DEFAULT_POST_QUERIES = [
    "linkedin.com/posts vaga desenvolvedor remoto email",
    "linkedin.com/posts vaga desenvolvedor junior remoto curriculo",
    "empregos.recrutei.com.br desenvolvedor remoto",
    "querohome.com.br desenvolvedor remoto junior",
]

# Sites agregadores que republicam vagas antigas ou páginas de listagem genérica
BLOCKED_DOMAINS = (
    "gupy.io",
    "vagas.com.br/vagas-em",
    "indeed.com",
    "catho.com.br",
    "glassdoor.com",
    "casado.dev",
    "talesaugusto.biz",
    "vagasremotas.net",
    "melhoresempregos.com",
    "linkedin.com/newsletters",
    "bairesdev",
)

OLD_DATE_PATTERNS = (
    "sep ",
    "set ",
    "aug ",
    "ago ",
    "jul ",
    "/09/2026",
    "/08/2026",
    "weeks ago",
    "month ago",
    "months ago",
    "semanas",
    "meses",
)


def _dynamic_queries() -> list[str]:
    try:
        from .. import resume
        prof = resume.get_profile()
        cargos = prof.get("cargos") or []
        if cargos:
            main = cargos[0]
            return [
                f"linkedin.com/posts vaga {main} remoto curriculo",
                f"empregos.recrutei.com.br {main} remoto",
                f"querohome.com.br {main} remoto",
            ] + DEFAULT_POST_QUERIES[:2]
    except Exception:
        pass
    return DEFAULT_POST_QUERIES


def _linkedin_job_is_open(c, jid: str) -> bool:
    """Consulta a API pública do LinkedIn para garantir que a vaga ainda aceita candidaturas e é recente."""
    try:
        r = c.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")
        if r.status_code != 200:
            return False
        low = r.text.lower()
        if "no longer accepting applications" in low or "closed-job__flavor--closed" in low:
            return False
        if any(w in low for w in ("weeks ago", "month ago", "months ago", "over 200 applicants")):
            return False
        return True
    except Exception:
        return False


def fetch(slug: str) -> list[Job]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []

    queries = _dynamic_queries() if slug == "default" else [slug]
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with DDGS() as ddgs, client() as c:
        for q in queries:
            try:
                # timelimit="w" = somente resultados publicados nos últimos 7 dias!
                results = list(ddgs.text(q, region="br-pt", timelimit="w", max_results=8))
            except Exception:
                continue

            for item in results:
                href = (item.get("href") or "").strip()
                title = (item.get("title") or "").strip()
                body = (item.get("body") or "").strip()
                if not href or href in seen_urls:
                    continue
                low_href = href.lower()
                low_body = f"{title} {body}".lower()

                if any(bad in low_href for bad in BLOCKED_DOMAINS):
                    continue
                if any(old in low_body for old in OLD_DATE_PATTERNS):
                    continue

                # Se o link do resultado for uma vaga do LinkedIn (/jobs/view/), verifica se está aberta!
                if m_li := LI_JOB_ID_RE.search(href):
                    jid = m_li.group(1)
                    if not _linkedin_job_is_open(c, jid):
                        continue
                    href = f"https://www.linkedin.com/jobs/view/{jid}"

                seen_urls.add(href)
                full_desc = body
                if any(d in low_href for d in ("querohome.com.br", "voudehome.com.br", "recrutei.com.br", "linkedin.com/posts")):
                    try:
                        r = c.get(href)
                        if r.status_code != 200:
                            continue
                        if "no longer accepting applications" in r.text.lower() or "vaga encerrada" in r.text.lower():
                            continue
                        # Se a página redireciona para uma vaga fechada do LinkedIn, confere também
                        if m_ext := LI_JOB_ID_RE.search(r.text):
                            if not _linkedin_job_is_open(c, m_ext.group(1)):
                                continue
                        extracted = html_to_text(r.text)
                        if len(extracted) > len(body):
                            full_desc = extracted[:4500]
                    except Exception:
                        pass

                emails = sorted(
                    set(
                        e
                        for e in EMAIL_RE.findall(f"{body} {full_desc}")
                        if not e.lower().endswith((".png", ".jpg", ".svg", "sentry.io", "example.com", "w3.org"))
                    )
                )
                email_tag = f" | ✉️ {emails[0]}" if emails else ""
                clean_title = re.sub(
                    r"\s*[-|—]\s*(LinkedIn.*|Quero Home.*|Vou de Home.*|Recrutei.*|InfoCarreira.*)$",
                    "",
                    title,
                    flags=re.I,
                ).strip()

                jobs.append(
                    Job(
                        title=clean_title or title,
                        url=href,
                        location=f"Brasil | Remoto (Post/Web){email_tag}",
                        description=f"{body}\n\n{full_desc}"
                        + (f"\n\nE-mails encontrados no post: {', '.join(emails)}" if emails else ""),
                        remote=True,
                    )
                )
            time.sleep(0.5)

    return jobs


def probe(slug: str) -> int:
    return 0
