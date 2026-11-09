"""Coleta de vagas remotas em PMEs e Software Houses brasileiras via Sólides (vagas.solides.com.br)."""
from datetime import datetime, timedelta, timezone
import json
import re

from .. import matching
from .base import Job, client, html_to_text

SEARCH_KEYWORDS = [
    "desenvolvedor",
    "programador",
    "php",
    "java",
    "frontend",
    "full-stack",
    "react",
    "angular",
    "javascript",
    "node",
    "laravel",
    "software",
]


def _resolve_flight_refs(full_stream: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for m in re.finditer(r"([0-9a-f]+):T([0-9a-f]+),", full_stream):
        ref_id = "$" + m.group(1)
        byte_len = int(m.group(2), 16)
        start_pos = m.end()
        sub = full_stream[start_pos : start_pos + byte_len + 100]
        raw_bytes = sub.encode("utf-8")[:byte_len]
        refs[ref_id] = raw_bytes.decode("utf-8", errors="ignore")
    return refs


def fetch(slug: str = "remoto") -> list[Job]:
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=150)).strftime("%Y-%m-%d")
    found: dict[str, Job] = {}

    with client(timeout=20.0) as c:
        for kw in SEARCH_KEYWORDS:
            for page in range(1, 4):
                url = f"https://vagas.solides.com.br/vagas/{kw}/remoto/todas"
                if page > 1:
                    url += f"?page={page}"
                try:
                    r = c.get(url)
                    if r.status_code != 200:
                        break
                except Exception:
                    break

                chunks = []
                for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', r.text):
                    try:
                        chunks.append(json.loads(m.group(1)))
                    except Exception:
                        pass
                full_stream = "".join(chunks)
                refs = _resolve_flight_refs(full_stream)

                m_init = re.search(r'"initialData":(\{"totalPages":.*?),"search":', full_stream)
                if not m_init:
                    break
                try:
                    data = json.loads(m_init.group(1))
                except Exception:
                    break

                items = data.get("data") or []
                if not items:
                    break

                hit_old = False
                for item in items:
                    jid = str(item.get("id") or "")
                    if not jid or jid in found:
                        continue
                    if item.get("isDisabled") or item.get("receivingResume") is False:
                        continue
                    comp_slug = (item.get("slug") or "").strip()
                    if comp_slug.startswith("desativado"):
                        continue
                    created_at = (item.get("createdAt") or "").strip()[:10]
                    if created_at and created_at < cutoff_date:
                        hit_old = True
                        continue
                    if item.get("jobType") != "remoto" and not item.get("homeOffice"):
                        continue

                    raw_title = (item.get("title") or "").strip()
                    if not raw_title:
                        continue

                    seniority_names = [
                        (s.get("name") or "").lower()
                        for s in (item.get("seniority") or [])
                        if isinstance(s, dict)
                    ]
                    sen_str = " ".join(seniority_names)
                    has_jr = any(k in sen_str for k in ("junior", "júnior", "estagi", "trainee", "aprendiz"))
                    has_sr_pl = any(k in sen_str for k in ("pleno", "senior", "sênior", "especialista", "coord", "gerente"))
                    if has_sr_pl and not has_jr:
                        continue

                    desc = item.get("description") or ""
                    if desc.startswith("$") and desc in refs:
                        desc = refs[desc]
                    clean_desc = html_to_text(desc)

                    skills = [
                        (s.get("name") or "").strip()
                        for s in (item.get("hardSkills") or [])
                        if isinstance(s, dict) and s.get("name")
                    ]
                    if skills:
                        clean_desc = f"Skills: {', '.join(skills)}\n{clean_desc}"

                    if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title, clean_desc):
                        continue

                    company = (item.get("companyName") or "").strip()
                    full_title = (
                        f"{raw_title} — {company}"
                        if company and company.lower() not in ("empresa confidencial", "") and company.lower() not in raw_title.lower()
                        else raw_title
                    )
                    job_url = (
                        f"https://{comp_slug}.vagas.solides.com.br/vaga/{jid}"
                        if comp_slug
                        else f"https://vagas.solides.com.br/vaga/{jid}"
                    )

                    found[jid] = Job(
                        title=full_title,
                        url=job_url,
                        location="Brasil | 100% Remoto",
                        description=clean_desc,
                        posted_at=created_at,
                        remote=True,
                    )

                if hit_old or page >= (data.get("totalPages") or 1):
                    break

    return list(found.values())

