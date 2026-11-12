from .. import matching
from .base import Job, client, html_to_text

API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"
SEARCH_API = "https://jobs.workable.com/api/v1/jobs"
SEARCH_KEYWORDS = [
    "desenvolvedor",
    "programador",
    "php",
    "java",
    "angular",
    "react",
    "react native",
    "mobile",
    "frontend",
    "full stack",
    "developer",
    "suporte",
    "support",
]


def _fetch_search_br() -> list[Job]:
    kept: dict[str, Job] = {}
    with client(timeout=20.0) as c:
        for kw in SEARCH_KEYWORDS:
            try:
                r = c.get(
                    SEARCH_API,
                    params={"query": kw, "workplace": "remote", "location": "Brazil"},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue

            for j in data.get("jobs", []):
                jid = str(j.get("id") or "")
                if not jid or jid in kept or j.get("workplace") != "remote":
                    continue
                loc = j.get("location") or {}
                if loc.get("countryName") not in ("Brazil", "Brasil"):
                    continue
                raw_title = (j.get("title") or "").strip()
                if not raw_title:
                    continue
                html_desc = "\n".join(
                    x
                    for x in (
                        j.get("description") or "",
                        j.get("requirementsSection") or "",
                        j.get("benefitsSection") or "",
                    )
                    if x
                )
                clean_desc = html_to_text(html_desc)
                if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title, clean_desc):
                    continue
                company = ((j.get("company") or {}).get("title") or "").strip()
                full_title = (
                    f"{raw_title} — {company}"
                    if company and company.lower() not in raw_title.lower()
                    else raw_title
                )
                url = (j.get("url") or "").strip()
                if not url:
                    continue
                kept[jid] = Job(
                    title=full_title,
                    url=url,
                    location="Brasil | Remote",
                    description=clean_desc,
                    posted_at=(j.get("created") or "")[:10],
                    remote=True,
                )
    return list(kept.values())


def fetch(slug: str) -> list[Job]:
    if slug == "search-br":
        return _fetch_search_br()
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
