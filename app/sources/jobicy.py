"""Coleta vagas 100% remotas abertas para Brasil e América Latina via API oficial do Jobicy."""
from .base import Job, client, html_to_text


def fetch(slug: str) -> list[Job]:
    geos = ["brazil", "latam"] if (not slug or slug in ("brazil", "default")) else [slug]
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client() as c:
        for geo in geos:
            try:
                r = c.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "geo": geo})
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue

            for item in data.get("jobs") or []:
                url = (item.get("url") or "").strip()
                title = (item.get("jobTitle") or "").strip()
                company = (item.get("companyName") or "").strip()
                if not url or not title or url in seen_urls or "gupy.io" in url.lower():
                    continue
                seen_urls.add(url)

                geo_label = item.get("jobGeo") or "Brazil / LATAM"
                level = item.get("jobLevel") or ""
                excerpt = html_to_text(item.get("jobExcerpt") or "")
                desc_html = item.get("jobDescription") or ""
                desc = html_to_text(desc_html) if desc_html else excerpt
                pub_date = (item.get("pubDate") or "")[:10]

                full_title = f"{title} — {company}" if company and company.lower() not in title.lower() else title
                jobs.append(
                    Job(
                        title=full_title,
                        url=url,
                        location=f"Remote | {geo_label}" + (f" ({level})" if level else ""),
                        description=desc,
                        posted_at=pub_date,
                        remote=True,
                    )
                )

    return jobs


def probe(slug: str) -> int:
    return 0

