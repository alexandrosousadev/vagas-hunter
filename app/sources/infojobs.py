"""Coleta de vagas Home Office / Remotas no InfoJobs (https://www.infojobs.com.br)."""
import time

from selectolax.lexbor import LexborHTMLParser

from .. import matching
from .base import Job, client

SEARCH_SLUGS = [
    "vagas-de-emprego-desenvolvedor-trabalho-home-office.aspx",
    "vagas-de-emprego-programador-trabalho-home-office.aspx",
    "vagas-de-emprego-java-trabalho-home-office.aspx",
    "vagas-de-emprego-php-trabalho-home-office.aspx",
    "vagas-de-emprego-angular-trabalho-home-office.aspx",
    "vagas-de-emprego-react-trabalho-home-office.aspx",
    "vagas-de-emprego-front+end-trabalho-home-office.aspx",
    "vagas-de-emprego-full+stack-trabalho-home-office.aspx",
    "vagas-de-emprego-mobile-trabalho-home-office.aspx",
    "vagas-de-emprego-suporte+tecnico-trabalho-home-office.aspx",
    "vagas-de-emprego-analista+de+suporte-trabalho-home-office.aspx",
    "vagas-de-emprego-help+desk-trabalho-home-office.aspx",
]


def fetch(slug: str = "remoto") -> list[Job]:
    candidates: dict[str, tuple[str, str, str]] = {}

    with client(timeout=20.0) as c:
        for path in SEARCH_SLUGS:
            url = f"https://www.infojobs.com.br/{path}"
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            tree = LexborHTMLParser(r.text)
            for card in tree.css("div.js_rowCard"):
                a = card.css_first("a[href^='/vaga-de-']")
                if not a:
                    continue
                href = (a.attributes.get("href") or "").split("?")[0].strip()
                if not href:
                    continue
                full_url = f"https://www.infojobs.com.br{href}" if href.startswith("/") else href
                if full_url in candidates:
                    continue

                raw_title = " ".join(a.text().split()).strip()
                if not raw_title:
                    continue
                if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title):
                    continue

                comp_el = card.css_first("div.text-body a")
                company = " ".join(comp_el.text().split()).strip() if comp_el else ""
                card_txt = " ".join(card.text(separator=" ").split())
                candidates[full_url] = (raw_title, company, card_txt)
            time.sleep(0.2)

        jobs: list[Job] = []
        for full_url, (raw_title, company, card_txt) in candidates.items():
            desc = card_txt
            try:
                r2 = c.get(full_url)
                if r2.status_code == 200:
                    t2 = LexborHTMLParser(r2.text)
                    panel = t2.css_first("div.js_vacancyDataPanels") or t2.css_first("p.js_vacancyDataPanels")
                    if panel:
                        desc = " ".join(panel.text(separator="\n").split())
            except Exception:
                pass

            if not matching.title_ok(raw_title, desc):
                continue

            low = f"{raw_title} {desc}".lower()
            if any(
                bad in low
                for bad in (
                    "modelo presencial",
                    "vaga presencial",
                    "100% presencial",
                    "atuação presencial",
                    "atuacao presencial",
                    "modelo híbrido",
                    "modelo hibrido",
                )
            ):
                if not any(ok in low for ok in ("100% home office", "100% remot", "totalmente remot")):
                    continue

            full_title = (
                f"{raw_title} — {company}"
                if company and company.lower() not in raw_title.lower()
                else raw_title
            )
            jobs.append(
                Job(
                    title=full_title,
                    url=full_url,
                    location="Brasil | Home Office",
                    description=desc[:4500],
                    remote=True,
                )
            )
            time.sleep(0.15)

    return jobs


def probe(slug: str) -> int:
    return len(fetch(slug))

