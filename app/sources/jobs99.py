"""Coleta de vagas remotas de TI na 99jobs (https://99jobs.com)."""
import time

from selectolax.lexbor import LexborHTMLParser

from .. import matching
from .base import Job, client

SEARCH_TERMS = [
    "desenvolvedor",
    "programador",
    "java",
    "php",
    "angular",
    "react",
    "mobile",
    "suporte",
    "tecnologia",
    "software",
]


def fetch(slug: str = "remoto") -> list[Job]:
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client(timeout=20.0) as c:
        for term in SEARCH_TERMS:
            try:
                r = c.get(
                    "https://99jobs.com/opportunities/filtered_search",
                    params={"utf8": "✓", "search[term]": term},
                )
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            tree = LexborHTMLParser(r.text)
            for card in tree.css("a.opportunity-card"):
                href = (card.attributes.get("href") or "").split("?")[0].strip()
                if not href:
                    continue
                full_url = f"https://99jobs.com{href}" if href.startswith("/") else href
                if full_url in seen_urls:
                    continue

                h1 = card.css_first("h1")
                raw_title = " ".join(h1.text().split()).strip() if h1 else ""
                if not raw_title:
                    continue

                mode_el = card.css_first(".opportunity-label-acting-mode")
                mode_txt = " ".join(mode_el.text().split()).strip() if mode_el else ""
                if "remot" not in mode_txt.lower() and "remot" not in raw_title.lower():
                    continue

                lvl_el = card.css_first(".opportunity-label-level")
                lvl_txt = " ".join(lvl_el.text().split()).strip() if lvl_el else ""
                lvl_low = lvl_txt.lower()
                if any(w in lvl_low for w in ("pleno", "sênior", "senior", "especialista", "gerência", "diretoria")):
                    if not any(w in lvl_low for w in ("júnior", "junior", "estágio", "estagio", "trainee")):
                        continue

                comp_el = card.css_first(".opportunity-company") or card.css_first("h2")
                company = " ".join(comp_el.text().split()).strip() if comp_el else ""
                desc = f"Nível: {lvl_txt} | Modalidade: {mode_txt} | Empresa: {company}"

                if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title, desc):
                    continue

                seen_urls.add(full_url)
                full_title = (
                    f"{raw_title} — {company}"
                    if company and company.lower() not in raw_title.lower()
                    else raw_title
                )
                jobs.append(
                    Job(
                        title=full_title,
                        url=full_url,
                        location=f"Brasil | {mode_txt or 'Remoto'}",
                        description=desc,
                        remote=True,
                    )
                )
            time.sleep(0.2)

    return jobs


def probe(slug: str) -> int:
    return len(fetch(slug))

