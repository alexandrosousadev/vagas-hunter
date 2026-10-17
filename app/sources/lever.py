from datetime import datetime, timezone

from .base import Job, client, html_to_text

API = "https://api.lever.co/v0/postings/{slug}"


def fetch(slug: str) -> list[Job]:
    with client() as c:
        r = c.get(API.format(slug=slug), params={"mode": "json"})
        r.raise_for_status()
        data = r.json()
    jobs = []
    for j in data:
        cat = j.get("categories") or {}
        locs = [cat.get("location", "")] + (cat.get("allLocations") or [])
        wt = j.get("workplaceType", "")
        lists = "\n\n".join(f"{l.get('text', '')}\n{html_to_text(l.get('content', ''))}" for l in j.get("lists", []))
        created = j.get("createdAt")
        jobs.append(Job(
            title=j["text"],
            url=j["hostedUrl"],
            location=" | ".join(x for x in dict.fromkeys(locs + [wt]) if x),
            description=(j.get("descriptionPlain") or "") + "\n\n" + lists,
            posted_at=datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else "",
            remote=True if wt == "remote" else None,
        ))
    return jobs


def probe(slug: str) -> int:
    with client() as c:
        r = c.get(API.format(slug=slug), params={"mode": "json"})
        return len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else 0
