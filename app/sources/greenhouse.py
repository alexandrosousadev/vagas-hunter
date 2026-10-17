from .base import Job, client, html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def fetch(slug: str) -> list[Job]:
    with client() as c:
        r = c.get(API.format(slug=slug), params={"content": "true"})
        r.raise_for_status()
        data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        locs = [(j.get("location") or {}).get("name", "")]
        locs += [o.get("name", "") for o in j.get("offices", [])]
        jobs.append(Job(
            title=j["title"],
            url=j["absolute_url"],
            location=" | ".join(x for x in dict.fromkeys(locs) if x),
            description=html_to_text(j.get("content", "")),
            posted_at=j.get("first_published") or j.get("updated_at", ""),
        ))
    return jobs


def probe(slug: str) -> int:
    with client() as c:
        r = c.get(API.format(slug=slug))
        return r.json().get("meta", {}).get("total", 0) if r.status_code == 200 else 0
