"""Coleta vagas 100% Home Office no portal brasileiro Vagas.com.br (sem login e sem Gupy)."""
import time
from urllib.parse import quote_plus
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client


DEFAULT_SLUGS = [
    "vagas-de-desenvolvedor?m%5B%5D=100%25+Home+Office",
    "vagas-de-programador?m%5B%5D=100%25+Home+Office",
    "vagas-de-java?m%5B%5D=100%25+Home+Office",
    "vagas-de-php?m%5B%5D=100%25+Home+Office",
    "vagas-de-front-end?m%5B%5D=100%25+Home+Office",
    "vagas-de-full-stack?m%5B%5D=100%25+Home+Office",
    "vagas-de-ti?m%5B%5D=100%25+Home+Office",
    "vagas-de-home-office",
]


def _slugs_from_profile() -> list[str]:
    """Adiciona buscas no Vagas.com.br baseadas nos cargos/skills do currículo ativo."""
    out: list[str] = []
    try:
        from .. import resume
        prof = resume.get_profile()
        terms = (prof.get("cargos") or [])[:4] + (prof.get("skills") or [])[:5]
        for t in terms:
            clean = t.strip().lower().replace(" ", "-")
            if len(clean) >= 2:
                s = f"vagas-de-{quote_plus(clean)}?m%5B%5D=100%25+Home+Office"
                if s not in out:
                    out.append(s)
    except Exception:
        pass
    for d in DEFAULT_SLUGS:
        if d not in out:
            out.append(d)
    return out[:10]


def fetch(slug: str) -> list[Job]:
    paths = _slugs_from_profile() if (not slug or slug == "remoto") else [slug]
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client() as c:
        for path in paths:
            url = f"https://www.vagas.com.br/{path.lstrip('/')}"
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
                tree = HTMLParser(r.text)
            except Exception:
                continue

            for li in tree.css("li.vaga"):
                a = li.css_first("a.link-detalhes-vaga")
                if not a:
                    continue
                href = (a.attributes.get("href") or "").strip()
                if not href:
                    continue
                full_url = f"https://www.vagas.com.br{href}" if href.startswith("/") else href
                if full_url in seen_urls or "gupy.io" in full_url.lower():
                    continue

                title = " ".join((a.text(strip=True) or "").split())
                if not title:
                    continue

                emp_el = li.css_first(".emprVaga")
                loc_el = li.css_first(".vaga-local")
                det_el = li.css_first(".detalhes")
                niv_el = li.css_first(".nivelVaga")

                company = " ".join((emp_el.text(strip=True) if emp_el else "").split())
                loc = " ".join((loc_el.text(strip=True) if loc_el else "100% Home Office").split())
                det = " ".join((det_el.text(strip=True) if det_el else "").split())
                nivel = " ".join((niv_el.text(strip=True) if niv_el else "").split())

                # Garante que não é vaga híbrida/presencial disfarçada
                combined = f"{title} {loc} {det}".lower()
                if "híbrid" in combined or "hibrid" in combined or "presencial" in combined:
                    if "100% home office" not in combined and "100% remot" not in combined:
                        continue

                seen_urls.add(full_url)
                full_title = f"{title} — {company}" if company and company.lower() not in title.lower() else title
                desc = f"Empresa: {company}\nNível: {nivel}\nModalidade: {loc}\n\n{det}"

                jobs.append(
                    Job(
                        title=full_title,
                        url=full_url,
                        location=f"Brasil | {loc or '100% Home Office'}",
                        description=desc,
                        remote=True,
                    )
                )
            time.sleep(0.25)

    return jobs


def probe(slug: str) -> int:
    return 0

