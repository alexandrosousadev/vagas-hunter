from .base import Job, client, html_to_text

API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


def fetch(slug: str) -> list[Job]:
    with client() as c:
        r = c.get(API.format(slug=slug), params={"details": "true"})
        r.raise_for_status()
        data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        locs = [", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)]
        locs += [", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in j.get("locations", [])]
        if j.get("telecommuting"):
            locs.append("Remote")
        jobs.append(Job(
            title=j["title"],
            url=j.get("url") or j.get("shortlink") or f"https://apply.workable.com/{slug}/j/{j['shortcode']}/",
            location=" | ".join(x for x in dict.fromkeys(locs) if x),
            description=html_to_text(j.get("description", "")),
            posted_at=j.get("published_on", ""),
            remote=True if j.get("telecommuting") else None,
        ))
    return jobs


def probe(slug: str) -> int:
    with client() as c:
        r = c.get(API.format(slug=slug))
        return len(r.json().get("jobs", [])) if r.status_code == 200 else 0
