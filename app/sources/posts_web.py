"""Busca vagas postadas em Posts/Feed do LinkedIn, portais de Home Office e páginas abertas com envio por e-mail
(usando busca web com extração automática de e-mail de RH no texto)."""
import re
import time

from .base import Job, client, html_to_text

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

DEFAULT_POST_QUERIES = [
    "linkedin.com/posts vaga desenvolvedor remoto email",
    "linkedin.com/posts vaga desenvolvedor junior remoto curriculo",
    "querohome.com.br desenvolvedor remoto junior",
    "voudehome.com.br vaga desenvolvedor remoto",
    "empregos.recrutei.com.br desenvolvedor remoto",
]


def _dynamic_queries() -> list[str]:
    try:
        from .. import resume
        prof = resume.get_profile()
        cargos = prof.get("cargos") or []
        if cargos:
            main = cargos[0]
            return [
                f"linkedin.com/posts vaga {main} remoto curriculo",
                f"querohome.com.br {main} remoto",
                f"empregos.recrutei.com.br {main} remoto",
            ] + DEFAULT_POST_QUERIES[:2]
    except Exception:
        pass
    return DEFAULT_POST_QUERIES


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
                results = list(ddgs.text(q, region="br-pt", timelimit="m", max_results=8))
            except Exception:
                continue

            for item in results:
                href = (item.get("href") or "").strip()
                title = (item.get("title") or "").strip()
                body = (item.get("body") or "").strip()
                if not href or href in seen_urls:
                    continue
                if any(bad in href.lower() for bad in ("gupy.io", "vagas.com.br/vagas-em", "indeed.com/l-", "catho.com.br", "glassdoor.com")):
                    continue

                seen_urls.add(href)
                full_desc = body
                if any(d in href for d in ("querohome.com.br", "voudehome.com.br", "recrutei.com.br", "linkedin.com/posts")):
                    try:
                        r = c.get(href)
                        if r.status_code == 200 and len(r.text) > 500:
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
                    r"\s*[-|—]\s*(LinkedIn.*|Quero Home.*|Vou de Home.*|Recrutei.*)$", "", title, flags=re.I
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

