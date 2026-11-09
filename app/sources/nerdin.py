"""Coleta vagas de TI home office no Nerdin (https://www.nerdin.com.br), usando o JSON-LD JobPosting de cada vaga."""
import json
import time

from selectolax.lexbor import LexborHTMLParser

from .. import matching
from .base import Job, client, html_to_text

BASE = "https://www.nerdin.com.br/"
LISTINGS = [
    "vagas-home-office.php",
    "vagas-estagio-junior.php",
    "vagas-desenvolvedor-sistemas.php",
    "vagas-full-stack.php",
    "vagas-python.php",
    "vagas-inteligencia-artificial.php",
]
MAX_PAGES = 4


def _job_posting(tree: LexborHTMLParser) -> dict:
    for s in tree.css("script[type='application/ld+json']"):
        try:
            data = json.loads(s.text())
        except Exception:
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
    return {}


def fetch(slug: str = "default") -> list[Job]:
    candidates: dict[str, tuple[str, str]] = {}
    with client() as c:
        for path in LISTINGS:
            for page in range(1, MAX_PAGES + 1):
                url = BASE + path + (f"?pagina={page}" if page > 1 else "")
                try:
                    r = c.get(url)
                    if r.status_code != 200:
                        break
                except Exception:
                    break
                cards = LexborHTMLParser(r.text).css("div.vaga-card")
                if not cards:
                    break
                for card in cards:
                    href = card.attributes.get("data-href") or ""
                    t = card.css_first(".vaga-titulo")
                    if not href or not t:
                        continue
                    title = " ".join(t.text(strip=True).replace("Nova", "").split()) if t else ""
                    meta = " ".join((card.css_first(".vaga-resumo-linha").text(strip=True) if card.css_first(".vaga-resumo-linha") else "").split())
                    full = BASE + href.lstrip("/")
                    if full in candidates or not title:
                        continue
                    if "home office" not in meta.lower() and "remot" not in meta.lower():
                        continue
                    if not matching.career_match_ok(title) or not matching.title_ok(title):
                        continue
                    candidates[full] = (title, meta)
                time.sleep(0.2)

        jobs: list[Job] = []
        for url, (title, meta) in candidates.items():
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
            except Exception:
                continue
            tree = LexborHTMLParser(r.text)
            jp = _job_posting(tree)
            desc = html_to_text(jp.get("description") or "")
            if not desc:
                continue
            if not matching.title_ok(title, desc):
                continue
            org = (jp.get("hiringOrganization") or {}).get("name") or ""
            full_title = f"{title} — {org}" if org and org.lower() not in title.lower() else title
            jobs.append(Job(
                title=full_title,
                url=url,
                location="Brasil | Home Office",
                description=f"{meta}\n{desc}",
                posted_at=(jp.get("datePosted") or "")[:10],
                remote=True,
            ))
            time.sleep(0.2)
    return jobs


def probe(slug: str) -> int:
    return 0

