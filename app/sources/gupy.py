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
    "Programador Junior",
    "Desenvolvedor Full Stack Junior",
    "Desenvolvedor Java Junior",
    "Desenvolvedor PHP Junior",
    "Desenvolvedor Front-end Junior",
    "Desenvolvedor Back-end Junior",
    "Desenvolvedor React Junior",
    "Desenvolvedor Angular Junior",
    "Desenvolvedor React Native",
    "Desenvolvedor Mobile",
    "Analista de Suporte Junior",
    "Suporte Tecnico",
    "Help Desk",
    "Service Desk",
    "Desenvolvedor Java",
    "Desenvolvedor PHP",
    "Desenvolvedor Angular",
    "Desenvolvedor Full Stack",
    "Desenvolvedor React",
    "Desenvolvedor Front-end",
    "Desenvolvedor Back-end",
]


def _terms_from_profile() -> list[str]:
    out: list[str] = list(DEFAULT_TERMS)
    try:
        from .. import resume
        prof = resume.get_profile()
        for role in (prof.get("cargos") or []) + (prof.get("cargos_semelhantes") or []):
            r = role.strip()
            if r and r not in out:
                out.append(r)
    except Exception:
        pass
    return out[:24]


def fetch(slug: str) -> list[Job]:
    terms = _terms_from_profile() if (not slug or slug in ("remoto", "default")) else [slug]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
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
                low_all = f"{name} {desc}".lower()
                if any(w in low_all for w in ("presencial", "híbrid", "hibrid", "residir em", "morar em")):
                    if not any(w in low_all for w in ("100% remot", "100% home office", "totalmente remot")):
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

