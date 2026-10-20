"""Coleta vagas 100% remotas no Portal Gupy (https://portal.gupy.io) filtradas por data e modalidade."""
from datetime import datetime, timedelta, timezone
import json
import time
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client

DEFAULT_TERMS = [
    "Desenvolvedor Junior",
    "Desenvolvedor Trainee",
    "Desenvolvedor Java",
    "Desenvolvedor PHP",
    "Desenvolvedor Angular",
    "Desenvolvedor Full Stack",
    "Desenvolvedor React",
    "Desenvolvedor Front-end",
    "Desenvolvedor Back-end",
    "Programador Junior",
]


def _terms_from_profile() -> list[str]:
    out: list[str] = []
    try:
        from .. import resume
        prof = resume.get_profile()
        for role in (prof.get("cargos") or []) + (prof.get("cargos_semelhantes") or []):
            r = role.strip()
            if r and r not in out:
                out.append(r)
        if prof.get("cargos") and prof.get("skills"):
            base = prof["cargos"][0].split()[0]
            for sk in (prof.get("skills") or [])[:5]:
                q = f"{base} {sk}"
                if q not in out:
                    out.append(q)
    except Exception:
        pass
    for d in DEFAULT_TERMS:
        if d not in out:
            out.append(d)
    return out[:11]


def fetch(slug: str) -> list[Job]:
    terms = _terms_from_profile() if (not slug or slug in ("remoto", "default")) else [slug]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=25)).strftime("%Y-%m-%d")
    seen_ids: set[int] = set()
    jobs: list[Job] = []

    with client() as c:
        for term in terms:
            url = f"https://portal.gupy.io/job-search/term={quote(term)}&workplaceTypes=remote"
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
                nd = HTMLParser(r.text).css_first("script#__NEXT_DATA__")
                if not nd:
                    continue
                items = (
                    json.loads(nd.text())
                    .get("props", {})
                    .get("pageProps", {})
                    .get("initialJobList", {})
                    .get("data", [])
                )
            except Exception:
                continue

            for item in items:
                jid = item.get("id")
                if not jid or jid in seen_ids:
                    continue
                if item.get("workplaceType") != "remote":
                    continue

                job_url = (item.get("jobUrl") or "").strip()
                if not job_url or "inactive" in job_url.lower():
                    continue
                # Limpa query param de tracking da Gupy
                clean_url = job_url.split("?")[0]

                pub = (item.get("publishedDate") or "")[:10]
                if pub and pub < cutoff:
                    continue

                name = (item.get("name") or "").strip()
                company = (item.get("careerPageName") or "").strip()
                desc = (item.get("description") or "").strip()
                if not name:
                    continue

                seen_ids.add(jid)
                full_title = f"{name} — {company}" if company and company.lower() not in name.lower() else name

                jobs.append(
                    Job(
                        title=full_title,
                        url=clean_url,
                        location=f"Brasil | 100% Remoto (Gupy • {pub or 'Recente'})",
                        description=desc,
                        posted_at=pub,
                        remote=True,
                    )
                )
            time.sleep(0.3)

    return jobs


def probe(slug: str) -> int:
    return 0
