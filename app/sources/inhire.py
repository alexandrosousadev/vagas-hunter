import time

from .base import Job, client, html_to_text

API = "https://api.inhire.app/job-posts/public/pages"


def _get(c, path: str, slug: str):
    r = c.get(API + path, headers={"X-Tenant": slug})
    r.raise_for_status()
    return r.json()


def fetch(slug: str) -> list[Job]:
    """A InHire lista as vagas sem descrição; o detalhe só é buscado para vagas remotas
    (as outras seriam descartadas pelo filtro de local de qualquer jeito)."""
    jobs = []
    with client() as c:
        data = _get(c, "", slug)
        for j in data.get("jobsPage", []):
            if j.get("status") != "published":
                continue
            wt = j.get("workplaceType") or ""
            job = Job(
                title=j["displayName"].strip(),
                url=f"https://{slug}.inhire.app/vagas/{j['jobId']}",
                location=" | ".join(x for x in (j.get("location"), wt) if x),
                remote=True if wt.lower() == "remote" else None,
            )
            if job.remote:
                try:
                    d = _get(c, f"/{j['jobId']}", slug)
                    job.description = html_to_text(d.get("description", ""))
                    job.posted_at = d.get("publishedAt") or d.get("createdAt", "")
                    time.sleep(0.2)
                except Exception:
                    pass
            jobs.append(job)
    return jobs


def probe(slug: str) -> int:
    with client() as c:
        r = c.get(API, headers={"X-Tenant": slug})
        return len(r.json().get("jobsPage", [])) if r.status_code == 200 else 0
