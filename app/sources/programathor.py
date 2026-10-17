"""Coleta vagas remotas no portal Programathor (https://programathor.com.br/jobs-city/remoto)."""
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client


def fetch(slug: str) -> list[Job]:
    """`slug` pode ser 'remoto' ou uma skill como 'java', 'php', 'angular'."""
    path = f"jobs-{slug}" if slug and slug != "remoto" else "jobs-city/remoto"
    url = f"https://programathor.com.br/{path}"
    with client() as c:
        r = c.get(url)
        if r.status_code != 200:
            return []
        tree = HTMLParser(r.text)

    jobs: list[Job] = []
    for cell in tree.css(".cell-list"):
        a = cell.css_first("a[href^='/jobs/']")
        h3 = cell.css_first("h3")
        if not a or not h3:
            continue
        href = a.attributes.get("href") or ""
        title = h3.text(strip=True)
        if not title or "vencida" in title.lower():
            continue

        spans = [s.text(strip=True) for s in cell.css(".cell-list-content-icon span") if s.text(strip=True)]
        company = spans[0] if spans else ""
        location = spans[1] if len(spans) > 1 else "Remoto"
        meta = " • ".join(spans)
        tags = [t.text(strip=True) for t in cell.css(".tag-list") if t.text(strip=True)]

        is_remote = "remot" in " ".join(spans).lower()
        full_title = f"{title} — {company}" if company and company.lower() not in title.lower() else title
        desc = f"Empresa: {company}\nDetalhes: {meta}\nSkills exigidas: {', '.join(tags)}"

        jobs.append(
            Job(
                title=full_title,
                url=f"https://programathor.com.br{href}",
                location=f"Brasil | {location}",
                description=desc,
                remote=is_remote,
            )
        )
    return jobs


def probe(slug: str) -> int:
    return 0

