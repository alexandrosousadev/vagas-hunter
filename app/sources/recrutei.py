"""Coleta de vagas remotas em PMEs e Software Houses brasileiras via Recrutei (empregos.recrutei.com.br)."""
from selectolax.lexbor import LexborHTMLParser

from .. import matching
from .base import Job, client

SEARCH_KEYWORDS = [
    "desenvolvedor",
    "programador",
    "php",
    "java",
    "full stack",
    "frontend",
    "front-end",
    "backend",
    "react",
    "react native",
    "mobile",
    "angular",
    "laravel",
    "suporte",
    "help desk",
]


def fetch(slug: str = "remoto") -> list[Job]:
    candidates: dict[str, tuple[str, str]] = {}

    with client(timeout=20.0) as c:
        for kw in SEARCH_KEYWORDS:
            try:
                r = c.get(
                    "https://empregos.recrutei.com.br/vagas",
                    params={"keyword": kw, "model": "remote"},
                )
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            tree = LexborHTMLParser(r.text)
            for row in tree.css("div.d2-jobrow__main"):
                a = row.css_first("h3.d2-jobrow__title a")
                if not a:
                    continue
                href = (a.attributes.get("href") or "").split("?")[0].strip()
                if not href or href in candidates:
                    continue
                raw_title = " ".join(a.text().split()).strip()
                if not raw_title:
                    continue
                if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title):
                    continue
                meta = row.css_first("p.d2-jobrow__meta")
                meta_txt = " ".join(meta.text().split()) if meta else ""
                company = meta_txt.split("·")[0].strip() if "·" in meta_txt else meta_txt
                candidates[href] = (raw_title, company)

        jobs: list[Job] = []
        for href, (raw_title, company) in candidates.items():
            try:
                r = c.get(href)
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            tree = LexborHTMLParser(r.text)
            desc_el = tree.css_first("article.d2-job-desc") or tree.css_first("div.d2-job-body")
            desc = " ".join(desc_el.text(separator=" ").split()) if desc_el else ""
            if not matching.title_ok(raw_title, desc):
                continue

            norm_desc = matching._norm(desc)
            if any(
                bad in norm_desc
                for bad in (
                    "atuacao hibrida",
                    "modelo hibrido",
                    "vaga hibrida",
                    "atuacao presencial",
                    "vaga presencial",
                    "100% presencial",
                )
            ):
                continue

            full_title = (
                f"{raw_title} — {company}"
                if company and company.lower() not in raw_title.lower()
                else raw_title
            )
            jobs.append(
                Job(
                    title=full_title,
                    url=href,
                    location="Brasil | 100% Remoto",
                    description=desc,
                    remote=True,
                )
            )

    return jobs

