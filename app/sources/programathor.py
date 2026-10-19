"""Coleta vagas remotas no portal Programathor (https://programathor.com.br/jobs-city/remoto e por stacks)."""
import time
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client

DEFAULT_PATHS = [
    "jobs-city/remoto",
    "jobs-java",
    "jobs-php",
    "jobs-angular",
    "jobs-react",
    "jobs-javascript",
    "jobs-node-js",
    "jobs-python",
]


def fetch(slug: str) -> list[Job]:
    """`slug` pode ser 'remoto' (varre a página remota + páginas de stacks) ou uma skill específica."""
    if not slug or slug == "remoto":
        paths = DEFAULT_PATHS
    else:
        paths = [f"jobs-{slug}" if not slug.startswith("jobs") else slug]

    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client() as c:
        for path in paths:
            url = f"https://programathor.com.br/{path}"
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
                tree = HTMLParser(r.text)
            except Exception:
                continue

            for cell in tree.css(".cell-list"):
                a = cell.css_first("a[href^='/jobs/']")
                h3 = cell.css_first("h3")
                if not a or not h3:
                    continue
                href = a.attributes.get("href") or ""
                full_url = f"https://programathor.com.br{href}"
                if full_url in seen_urls:
                    continue

                title = h3.text(strip=True)
                if not title or "vencida" in title.lower():
                    continue

                spans = [s.text(strip=True) for s in cell.css(".cell-list-content-icon span") if s.text(strip=True)]
                company = spans[0] if spans else ""
                location = spans[1] if len(spans) > 1 else "Remoto"
                meta = " • ".join(spans)
                tags = [t.text(strip=True) for t in cell.css(".tag-list") if t.text(strip=True)]

                is_remote = "remot" in " ".join(spans).lower() or path == "jobs-city/remoto"
                if not is_remote:
                    continue

                seen_urls.add(full_url)
                full_title = f"{title} — {company}" if company and company.lower() not in title.lower() else title
                desc = f"Empresa: {company}\nDetalhes: {meta}\nSkills exigidas: {', '.join(tags)}"

                jobs.append(
                    Job(
                        title=full_title,
                        url=full_url,
                        location=f"Brasil | {location}",
                        description=desc,
                        remote=True,
                    )
                )
            time.sleep(0.25)

    return jobs


def probe(slug: str) -> int:
    return 0

