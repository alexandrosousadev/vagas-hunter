"""Coleta vagas Home Office na Catho (https://www.catho.com.br/vagas/...-home-office/)."""
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client

DEFAULT_SLUGS = [
    "desenvolvedor-junior-home-office",
    "desenvolvedor-trainee-home-office",
    "desenvolvedor-java-home-office",
    "desenvolvedor-php-home-office",
    "desenvolvedor-angular-home-office",
    "desenvolvedor-react-home-office",
    "desenvolvedor-full-stack-home-office",
    "desenvolvedor-front-end-home-office",
    "programador-home-office",
]

# Ignora vagas publicadas em meses antigos (ex.: /01 a /09 quando estamos em /10)
OLD_MONTH_RE = re.compile(r"(?:Publicada|Atualizada)\s+em\s+\d{1,2}/0[1-9]\b", re.I)


def fetch(slug: str) -> list[Job]:
    slugs = DEFAULT_SLUGS if (not slug or slug in ("remoto", "default")) else [slug]
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client() as c:
        for s in slugs:
            url = f"https://www.catho.com.br/vagas/{s.strip('/')}/"
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
                tree = HTMLParser(r.text)
            except Exception:
                continue

            for art in tree.css("li article"):
                a = art.css_first("h2 a")
                if not a:
                    continue
                href = (a.attributes.get("href") or "").strip()
                title = " ".join((a.text(separator=" ", strip=True) or "").split())
                if not href or not title:
                    continue
                full_url = f"https://www.catho.com.br{href}" if href.startswith("/") else href
                clean_url = full_url.split("?")[0]
                if clean_url in seen_urls:
                    continue

                card_text = " ".join(art.text(separator=" | ", strip=True).split())
                if OLD_MONTH_RE.search(card_text):
                    continue

                # Extrai data de publicação se presente
                m_date = re.search(r"((?:Publicada|Atualizada)\s+em\s+\d{1,2}/\d{2}|Hoje|Ontem)", card_text, re.I)
                date_label = m_date.group(1) if m_date else "Recente"

                seen_urls.add(clean_url)
                jobs.append(
                    Job(
                        title=title,
                        url=clean_url,
                        location=f"Brasil | Home Office ({date_label})",
                        description=card_text,
                        remote=True,
                    )
                )
            time.sleep(0.35)

    return jobs


def probe(slug: str) -> int:
    return 0
