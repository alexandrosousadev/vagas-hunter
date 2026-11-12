"""Coleta de vagas remotas de TI na GeekHunter (https://www.geekhunter.com/pt/vagas)."""
import time

from selectolax.lexbor import LexborHTMLParser

from .. import matching
from .base import Job, client

MAX_PAGES = 8


def fetch(slug: str = "remoto") -> list[Job]:
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    with client(timeout=20.0) as c:
        for page in range(1, MAX_PAGES + 1):
            url = "https://www.geekhunter.com/pt/vagas" + (f"?page={page}" if page > 1 else "")
            try:
                r = c.get(url)
                if r.status_code != 200:
                    break
            except Exception:
                break

            tree = LexborHTMLParser(r.text)
            links = tree.css("a[href*='/jobs/']")
            if not links:
                break

            for a in links:
                href = (a.attributes.get("href") or "").split("?")[0].strip()
                if not href or href in seen_urls:
                    continue
                raw_title = " ".join(a.text().split()).strip()
                if not raw_title:
                    continue

                card = a.parent
                while card and card.tag != "body" and "css-ow7sdf" not in (card.attributes.get("class") or ""):
                    card = card.parent
                if not card:
                    continue

                card_txt = " ".join(card.text(separator=" | ").split())
                card_low = card_txt.lower()
                if "remoto" not in card_low and "remote" not in card_low:
                    continue

                has_jr = any(k in card_low for k in ("júnior", "junior", "trainee", "estágio", "estagio"))
                has_sr_pl = any(k in card_low for k in ("pleno", "sênior", "senior", "especialista", "tech lead"))
                if has_sr_pl and not has_jr:
                    continue

                sib = card.next
                while sib and sib.tag is None:
                    sib = sib.next
                req_txt = " ".join(sib.text(separator=" | ").split()) if sib else ""
                full_desc = f"{card_txt}\n{req_txt}".strip()

                if not matching.career_match_ok(raw_title) or not matching.title_ok(raw_title, full_desc):
                    continue

                seen_urls.add(href)
                jobs.append(
                    Job(
                        title=f"{raw_title} — GeekHunter",
                        url=href,
                        location="Brasil | 100% Remoto",
                        description=full_desc,
                        remote=True,
                    )
                )
            time.sleep(0.2)

    return jobs


def probe(slug: str) -> int:
    return len(fetch(slug))

