"""Coleta vagas de TI 100% Remotas / Home Office no APInfo (https://www.apinfo.com)."""
import re
import time

from selectolax.lexbor import LexborHTMLParser

from .. import matching
from .base import Job, client

SEARCH_TERMS = [
    "",
    "junior",
    "php",
    "java",
    "angular",
    "react",
    "mobile",
    "full stack",
    "front end",
    "back end",
    "desenvolvedor",
    "programador",
    "suporte",
    "help desk",
    "service desk",
    "sustentacao",
]

REMOTE_PATTERNS = (
    "home office",
    "home-office",
    " - ho -",
    "remoto",
    "remota",
    "100% remoto",
    "trabalho remoto",
    "atuacao remota",
    "modelo remoto",
)

ONSITE_PATTERNS = (
    "presencial",
    "hibrid",
    "híbrid",
    "dias no escritorio",
    "atuação híbrida",
    "atuacao hibrida",
)


def _parse_apinfo_date(info_text: str) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})\b", info_text)
    if not m:
        return ""
    dd, mm, yy = m.group(1), m.group(2), m.group(3)
    return f"20{yy}-{mm}-{dd}"


def fetch(slug: str = "remoto") -> list[Job]:
    found: dict[str, Job] = {}

    with client(timeout=20.0) as c:
        for kw in SEARCH_TERMS:
            try:
                data = {"estado[]": "HO", "onde": "2", "andor": "2"}
                if kw:
                    data["keyw"] = kw
                r = c.post("https://www.apinfo.com/apinfo/inc/list4.cfm", data=data)
                if r.status_code != 200:
                    continue
                html = r.content.decode("latin-1", errors="ignore")
            except Exception:
                continue

            tree = LexborHTMLParser(html)
            for box in tree.css("div.box-vagas"):
                cargo_el = box.css_first(".cargo")
                info_el = box.css_first(".info-data")
                texto_el = box.css_first(".texto")
                if not cargo_el or not texto_el:
                    continue

                raw_title = " ".join(cargo_el.text().split()).strip()
                info_txt = " ".join(info_el.text().split()).strip() if info_el else ""
                desc_txt = " ".join(texto_el.text(separator="\n").split()).strip()
                if not raw_title or not desc_txt:
                    continue

                m_cod = re.search(r"C[óo]digo\s*\.+\s*:\s*(\d+)", desc_txt, re.I)
                cod = m_cod.group(1) if m_cod else raw_title
                if cod in found:
                    continue

                combined_low = f"{info_txt} {raw_title} {desc_txt}".lower()
                if not any(p in combined_low for p in REMOTE_PATTERNS):
                    continue
                if any(p in combined_low for p in ONSITE_PATTERNS):
                    if not any(p in combined_low for p in ("100% remot", "100% home office", "totalmente remot")):
                        continue

                if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title, desc_txt):
                    continue

                m_emp = re.search(r"Empresa\s*\.+\s*:\s*([^\n\r]+?)(?:\s+C[óo]digo|\s*$)", desc_txt, re.I)
                company = m_emp.group(1).strip() if m_emp else ""
                full_title = (
                    f"{raw_title} — {company}"
                    if company and company.lower() not in raw_title.lower()
                    else raw_title
                )

                url = f"https://www.apinfo.com/apinfo/inc/list4.cfm?keyw={cod}"
                posted_at = _parse_apinfo_date(info_txt)

                found[cod] = Job(
                    title=full_title,
                    url=url,
                    location=f"Brasil | Home Office ({info_txt.split('-')[0].strip() or 'BR'})",
                    description=f"{info_txt}\n{desc_txt}",
                    posted_at=posted_at,
                    remote=True,
                )
            time.sleep(0.2)

    return list(found.values())


def probe(slug: str) -> int:
    return len(fetch(slug))
