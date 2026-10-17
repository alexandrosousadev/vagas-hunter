"""Coleta vagas abertas nos repositórios comunitários brasileiros do GitHub
(ex: backend-br/vagas, frontendbr/vagas, phpdevbr/vagas, react-brasil/vagas).
"""
from .base import Job, client


def fetch(slug: str) -> list[Job]:
    """`slug` é o 'owner/repo', ex: 'backend-br/vagas'."""
    url = f"https://api.github.com/repos/{slug}/issues"
    with client() as c:
        r = c.get(url, params={"state": "open", "per_page": 60, "sort": "created", "direction": "desc"})
        if r.status_code != 200:
            return []
        data = r.json()

    jobs: list[Job] = []
    for issue in data:
        if "pull_request" in issue:
            continue
        title = (issue.get("title") or "").strip()
        body = (issue.get("body") or "").strip()
        labels = [lb.get("name", "") for lb in (issue.get("labels") or [])]
        label_str = " | ".join(labels)

        # Verifica se é remota pelo título, labels ou corpo (e descarta híbrido/presencial puro)
        combined = f"{title} {label_str}".lower()
        has_remote = any(w in combined for w in ("remot", "home office", "anywhere", "100% remoto"))
        only_hybrid_or_onsite = any(w in combined for w in ("híbrid", "hibrid", "presencial")) and not has_remote
        if only_hybrid_or_onsite:
            continue
        loc = f"Brasil | {label_str}" if label_str else ("Remoto | Brasil" if has_remote else "Brasil")

        jobs.append(
            Job(
                title=title,
                url=issue.get("html_url") or "",
                location=loc,
                description=f"Labels: {label_str}\n\n{body}",
                posted_at=issue.get("created_at") or "",
                remote=True if has_remote else None,
            )
        )
    return jobs


def probe(slug: str) -> int:
    return 0

