from .base import Job, client

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch(slug: str) -> list[Job]:
    with client() as c:
        r = c.get(API.format(slug=slug))
        r.raise_for_status()
        data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
        if j.get("workplaceType"):
            locs.append(j["workplaceType"])
        jobs.append(Job(
            title=j["title"],
            url=j["jobUrl"],
            location=" | ".join(x for x in dict.fromkeys(locs) if x),
            description=j.get("descriptionPlain", ""),
            posted_at=j.get("publishedAt", ""),
            remote=True if j.get("isRemote") else None,
        ))
    return jobs


def probe(slug: str) -> int:
    with client() as c:
        r = c.get(API.format(slug=slug))
        return len(r.json().get("jobs", [])) if r.status_code == 200 else 0
