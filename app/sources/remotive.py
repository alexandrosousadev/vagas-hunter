"""Coleta vagas 100% remotas via API oficial da Remotive (filtradas para Brasil, LATAM ou Worldwide)."""
from .base import Job, client, html_to_text

ALLOWED_LOCS = (
    "brazil",
    "brasil",
    "latam",
    "latin america",
    "south america",
    "americas",
    "worldwide",
    "anywhere",
)


def fetch(slug: str) -> list[Job]:
    categories = ["software-dev", "qa", "data", "customer-support"] if (not slug or slug == "default") else [slug]
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client() as c:
        for cat in categories:
            try:
                r = c.get("https://remotive.com/api/remote-jobs", params={"category": cat, "limit": 60})
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue

            for item in data.get("jobs") or []:
                loc = (item.get("candidate_required_location") or "Worldwide").strip()
                loc_low = loc.lower()
                if not any(a in loc_low for a in ALLOWED_LOCS):
                    continue

                url = (item.get("url") or "").strip()
                title = (item.get("title") or "").strip()
                company = (item.get("company_name") or "").strip()
                if not url or not title or url in seen_urls or "gupy.io" in url.lower():
                    continue
                seen_urls.add(url)

                desc = html_to_text(item.get("description") or "")
                pub_date = (item.get("publication_date") or "")[:10]
                full_title = f"{title} — {company}" if company and company.lower() not in title.lower() else title

                jobs.append(
                    Job(
                        title=full_title,
                        url=url,
                        location=f"Remote | {loc}",
                        description=desc,
                        posted_at=pub_date,
                        remote=True,
                    )
                )

    return jobs


def probe(slug: str) -> int:
    return 0

