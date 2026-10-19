"""Coleta vagas 100% remotas de nível Júnior no Brasil do índice eu.dev.br (que monitora +900 empresas diariamente).
Extrai a descrição estruturada (JobPosting JSON-LD) e o link direto do ATS da empresa."""
import concurrent.futures
import json
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client


def _fetch_detail(c, path: str, fallback_title: str, company: str, ago: str) -> Job | None:
    url = f"https://eu.dev.br{path}"
    try:
        r = c.get(url)
        if r.status_code != 200:
            return None
        tree = HTMLParser(r.text)
    except Exception:
        return None

    desc = ""
    title = fallback_title
    posted_at = ""
    for s in tree.css("script"):
        txt = s.text() or ""
        if '"JobPosting"' in txt:
            try:
                data = json.loads(txt)
                title = data.get("title") or title
                desc = data.get("description") or ""
                posted_at = (data.get("datePosted") or "")[:10]
            except Exception:
                pass
            break

    # Pega o link direto para o ATS da empresa ("candidatar agora →") se disponível
    direct_url = url
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if href.startswith("http") and "eu.dev.br" not in href and "candidatar" in a.text(strip=True).lower():
            if "gupy.io" in href.lower():
                return None
            direct_url = href
            break

    full_title = f"{title} — {company.title()}" if company and company.lower() not in title.lower() else title
    loc = f"Brasil | Remoto ({ago})" if ago else "Brasil | Remoto"
    return Job(
        title=full_title,
        url=direct_url,
        location=loc,
        description=desc or full_title,
        posted_at=posted_at,
        remote=True,
    )


def fetch(slug: str) -> list[Job]:
    """`slug` padrão: 'junior-remoto'."""
    page_slug = slug or "junior-remoto"
    list_url = f"https://eu.dev.br/vagas/{page_slug}/"
    with client() as c:
        r = c.get(list_url)
        if r.status_code != 200:
            return []
        tree = HTMLParser(r.text)

        by_href: dict[str, list[str]] = {}
        for a in tree.css("a"):
            href = a.attributes.get("href") or ""
            if (
                href.startswith("/vagas/")
                and href.count("/") == 3
                and not any(x in href for x in ("/nivel/", "/tipo/", "/empresa/", f"/{page_slug}/"))
            ):
                txt = a.text(strip=True)
                if txt:
                    by_href.setdefault(href, []).append(txt)

        candidates = []
        from .. import matching
        for href, texts in list(by_href.items())[:45]:
            # Ex: ['OPEN', 'há 3 dias', 'JR', 'desenvolvedor full-stack júnior // full-stack· greenhouse · júnior', 'greenhouse']
            ago = next((t for t in texts if t.startswith("há ") or "dia" in t or "hora" in t), "")
            company = texts[-1] if len(texts) >= 2 else ""
            raw_title = next((t for t in texts if "//" in t), texts[-2] if len(texts) >= 2 else href)
            clean_title = raw_title.split("//")[0].strip().title()
            if not matching.title_ok(clean_title):
                continue
            candidates.append((href, clean_title, company, ago))

        jobs: list[Job] = []
        for href, clean_title, company, ago in candidates[:30]:
            j = _fetch_detail(c, href, clean_title, company, ago)
            if j:
                jobs.append(j)
            time.sleep(0.15)

    return jobs


def probe(slug: str) -> int:
    return 0

