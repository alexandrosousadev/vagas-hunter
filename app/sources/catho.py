"""Coleta vagas Home Office na Catho (https://www.catho.com.br/vagas/...-home-office/),
abrindo a página da vaga para confirmar que é realmente 100% Home Office / Remota."""
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Job, client, html_to_text

DEFAULT_SLUGS = [
    "desenvolvedor-junior-home-office",
    "desenvolvedor-trainee-home-office",
    "desenvolvedor-java-home-office",
    "desenvolvedor-php-home-office",
    "desenvolvedor-angular-home-office",
    "desenvolvedor-react-home-office",
    "desenvolvedor-full-stack-home-office",
    "desenvolvedor-front-end-home-office",
    "programador-home-office",
]

OLD_MONTH_RE = re.compile(r"(?:Publicada|Atualizada)\s+em\s+\d{1,2}/0[1-9]\b", re.I)
ONSITE_WORDS = ("presencial", "híbrid", "hibrid", "residir em", "morar em", "atuação híbrida", "modelo híbrido")
REMOTE_WORDS = ("home office", "home-office", "100% remoto", "trabalho remoto", "modelo remoto", "totalmente remoto", "vaga remota", "atuacao remota", "atuação remota")


def _verify_catho_detail(c, url: str, title: str) -> tuple[bool, str]:
    """Abre a página da vaga na Catho e confirma se o texto realmente diz Home Office/Remoto sem exigir presencial/híbrido."""
    try:
        r = c.get(url)
        if r.status_code != 200:
            return False, ""
        txt = html_to_text(r.text)
        # Corta apenas a seção principal "Sobre a vaga" até "Vagas similares"
        main_txt = txt
        if "Sobre a vaga" in txt:
            main_txt = txt.split("Sobre a vaga", 1)[1]
        if "Vagas similares" in main_txt:
            main_txt = main_txt.split("Vagas similares", 1)[0]

        low = f"{title} {main_txt}".lower()
        if any(w in low for w in ONSITE_WORDS):
            if not any(w in low for w in ("100% home office", "100% remot", "totalmente remot")):
                return False, ""
        if not any(w in low for w in REMOTE_WORDS):
            return False, ""
        return True, main_txt.strip()[:4000]
    except Exception:
        return False, ""


def fetch(slug: str) -> list[Job]:
    slugs = DEFAULT_SLUGS if (not slug or slug in ("remoto", "default")) else [slug]
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client() as c:
        for s in slugs:
            url = f"https://www.catho.com.br/vagas/{s.strip('/')}/"
            try:
                r = c.get(url)
                if r.status_code != 200:
                    continue
                tree = HTMLParser(r.text)
            except Exception:
                continue

            for art in tree.css("li article"):
                a = art.css_first("h2 a")
                if not a:
                    continue
                href = (a.attributes.get("href") or "").strip()
                title = " ".join((a.text(separator=" ", strip=True) or "").split())
                if not href or not title:
                    continue
                full_url = f"https://www.catho.com.br{href}" if href.startswith("/") else href
                clean_url = full_url.split("?")[0]
                if clean_url in seen_urls:
                    continue

                card_text = " ".join(art.text(separator=" | ", strip=True).split())
                if OLD_MONTH_RE.search(card_text):
                    continue

                from .. import matching
                if not matching.title_ok(title):
                    continue

                seen_urls.add(clean_url)
                ok_remote, desc = _verify_catho_detail(c, clean_url, title)
                time.sleep(0.25)
                if not ok_remote:
                    continue

                m_date = re.search(r"((?:Publicada|Atualizada)\s+em\s+\d{1,2}/\d{2}|Hoje|Ontem)", card_text, re.I)
                date_label = m_date.group(1) if m_date else "Recente"

                jobs.append(
                    Job(
                        title=title,
                        url=clean_url,
                        location=f"Brasil | 100% Home Office ({date_label})",
                        description=desc or card_text,
                        remote=True,
                    )
                )
            time.sleep(0.3)

    return jobs


def probe(slug: str) -> int:
    return 0
