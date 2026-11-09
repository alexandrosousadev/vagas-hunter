"""Página de carreiras própria da Mosyle (Apple Device Management, time de dev no Brasil).

A página https://mosyle.com/careers lista as vagas em <li class="role-item">, com título,
descrição curta, modelo de trabalho e local de residência exigido.
"""
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client

CAREERS_URL = "https://mosyle.com/careers"


def fetch(slug: str = "default") -> list[Job]:
    url = slug if slug.startswith("http") else CAREERS_URL
    with client() as c:
        r = c.get(url)
        r.raise_for_status()
    tree = HTMLParser(r.text)
    jobs: list[Job] = []
    for li in tree.css("li.role-item"):
        title_el = li.css_first(".role-title")
        if not title_el:
            continue
        title = re.sub(r"\s+", " ", title_el.text(strip=True).replace("\xa0", " ")).strip()
        desc_el = li.css_first(".role-description")
        desc = re.sub(r"[ \t]+", " ", desc_el.text(separator="\n")).strip() if desc_el else ""
        locs = [s.text(strip=True) for s in li.css(".role-location")]
        anchor = li.css_first("a.apply-now")
        href = (anchor.attributes.get("href") or "") if anchor else ""
        data_id = li.attributes.get("data-id") or ""
        job_url = f"{CAREERS_URL}{href}" if href.startswith("#") else (href or f"{CAREERS_URL}#{data_id}")

        low = desc.lower()
        remote = "remote position" in low or "remote role" in low or "fully remote" in low
        if any(w in low for w in ("hybrid", "on-site", "onsite")):
            remote = False
        country = (li.attributes.get("data-country") or "").upper()
        loc = " | ".join(locs) or ("Brasil" if country == "BR" else country)
        loc = f"{loc} | {'Remoto' if remote else 'Presencial/Híbrido'}"

        jobs.append(Job(title=title, url=job_url, location=loc, description=desc, remote=remote))
    return jobs


def probe(slug: str) -> int:
    return len(fetch(slug))
