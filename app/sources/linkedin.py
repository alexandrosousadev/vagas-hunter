"""Busca pública do LinkedIn (sem login / guest API) para vagas remotas no Brasil.

Usa os endpoints públicos:
- Lista: https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
- Detalhe: https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>
"""
from datetime import datetime, timedelta, timezone
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..config import CFG
from .base import Job, client, html_to_text

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"

DEFAULT_QUERIES = [
    '"Remoto" Desenvolvedor Java Junior',
    '"Remoto" Desenvolvedor PHP Junior',
    '"Remoto" Desenvolvedor Angular Junior',
    '"Remoto" Desenvolvedor Full Stack Junior',
    '"Remoto" Desenvolvedor React Junior',
    '"Home Office" Desenvolvedor Junior',
    '"Remote" Java Angular Brazil',
    '"Remoto" PHP Laravel',
]

# Palavras que confirmam que a vaga é remota
REMOTE_CONFIRM = ("remot", "home office", "home-office", "anywhere", "teletrabalho", "100% remoto", "trabalho remoto")
# Palavras que denunciam vaga presencial ou híbrida disfarçada de remota no LinkedIn
ONSITE_CONFIRM = (
    "presencial",
    "hibrid",
    "híbrid",
    "hybrid",
    "on-site",
    "onsite",
    "residir em",
    "morar em",
    "disponibilidade para residir",
    "atuacao presencial",
    "atuação presencial",
    "modelo presencial",
)


def _is_truly_remote(title: str, location: str, desc: str) -> bool:
    """No LinkedIn, empresas costumam marcar vagas presenciais como 'Remoto' por engano.
    Valida se a vaga realmente é remota olhando título, local e descrição."""
    full = f"{title} {desc}".lower()
    loc_low = (location or "").lower()

    # Se menciona presencial/híbrido/residir em na descrição ou título, descarta
    if any(w in full for w in ONSITE_CONFIRM):
        # Só salva se disser explicitamente "100% remoto" ou "totalmente remoto"
        if not any(w in full for w in ("100% remot", "totalmente remot", "fully remote")):
            return False

    # Se o texto confirma remoto no título ou na descrição, aceita
    if any(w in full for w in REMOTE_CONFIRM):
        return True

    # Se a localização do card é genérica "Brazil" ou "Brasil" (sem cidade específica) e não tem indício presencial, aceita
    if loc_low.strip() in ("brazil", "brasil", "remote", "remoto"):
        return True

    # Caso contrário (tem cidade específica como "Assis, São Paulo, Brazil" e não menciona remoto em lugar nenhum da descrição), é vaga presencial!
    return False


def _parse_applicants(text: str) -> tuple[int | None, bool]:
    """Extrai o número aproximado de candidatos do texto do LinkedIn."""
    if not text:
        return None, False
    t = text.lower()
    is_over = any(w in t for w in ("over", "mais de", "+"))
    m = re.search(r"(\d+)", t)
    if not m:
        return None, False
    n = int(m.group(1))
    if "first 25" in t or "primeiros 25" in t:
        return 15, False
    return n, is_over


def _fetch_detail(c, job_id: str) -> tuple[str, int | None, bool, str]:
    for attempt in range(3):
        try:
            r = c.get(DETAIL_URL.format(job_id))
            if r.status_code == 429:
                time.sleep(1.3 * (attempt + 1))
                continue
            if r.status_code != 200:
                return "", None, False, ""
            tree = HTMLParser(r.text)
            desc_node = tree.css_first(".show-more-less-html__markup") or tree.css_first(".description__text")
            desc = html_to_text(desc_node.html) if desc_node else ""

            app_node = tree.css_first(".num-applicants__caption")
            app_txt = app_node.text(strip=True) if app_node else ""
            num_app, is_over = _parse_applicants(app_txt)

            ago_node = tree.css_first(".posted-time-ago__text")
            ago_txt = ago_node.text(strip=True) if ago_node else ""

            return desc, num_app, is_over, ago_txt
        except Exception:
            return "", None, False, ""
    return "", None, False, ""


def fetch(slug: str) -> list[Job]:
    """`slug` pode ser 'default' (usa queries do config.yaml) ou uma query específica."""
    li_cfg = CFG.get("linkedin", {})
    if slug and slug != "default":
        queries = [slug]
    else:
        queries = li_cfg.get("queries") or DEFAULT_QUERIES

    max_per_query = int(li_cfg.get("max_por_busca", 25))
    max_days = int(li_cfg.get("ultimos_dias", 5))
    max_applicants = int(li_cfg.get("max_candidatos", 100))
    exclude_companies = [
        x.lower()
        for x in li_cfg.get(
            "excluir_empresas",
            ["bairesdev", "crossover", "turing", "jobgether", "jobbol", "netvagas", "trabalha brasil", "empregos.com"],
        )
    ]
    only_recent_seconds = max_days * 86400
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=max_days)).strftime("%Y-%m-%d")

    seen_ids: set[str] = set()
    raw_cards: list[dict] = []

    with client() as c:
        for q in queries:
            params = {
                "keywords": q,
                "location": "Brazil",
                "f_WT": "2",  # 2 = Remote no LinkedIn
                "f_TPR": f"r{only_recent_seconds}",
                "start": 0,
            }
            try:
                r = c.get(SEARCH_URL, params=params)
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            tree = HTMLParser(r.text)
            count = 0
            for li in tree.css("li"):
                if count >= max_per_query:
                    break
                card = li.css_first("[data-entity-urn]")
                if not card:
                    continue
                urn = card.attributes.get("data-entity-urn") or ""
                jid = urn.split(":")[-1].strip()
                if not jid or not jid.isdigit() or jid in seen_ids:
                    continue

                title_el = li.css_first(".base-search-card__title")
                comp_el = li.css_first(".base-search-card__subtitle")
                loc_el = li.css_first(".job-search-card__location")
                time_el = li.css_first("time")
                benefit_el = li.css_first(".job-posting-benefits__text")

                title = title_el.text(strip=True) if title_el else ""
                comp = comp_el.text(strip=True) if comp_el else ""
                loc = loc_el.text(strip=True) if loc_el else "Brazil"
                posted = (time_el.attributes.get("datetime") or "") if time_el else ""
                benefit = benefit_el.text(strip=True) if benefit_el else ""
                clean_url = f"https://www.linkedin.com/jobs/view/{jid}"

                if not title:
                    continue
                if any(ex in comp.lower() for ex in exclude_companies):
                    continue
                if posted and posted < cutoff_date:
                    continue

                seen_ids.add(jid)
                count += 1
                raw_cards.append({
                    "jid": jid,
                    "title": f"{title} — {comp}" if comp and comp.lower() not in title.lower() else title,
                    "url": clean_url,
                    "raw_loc": loc,
                    "posted_at": posted,
                    "early": "early applicant" in benefit.lower(),
                })
            time.sleep(0.4)

        from .. import matching
        filtered_cards = [item for item in raw_cards if matching.title_ok(item["title"])]

        jobs: list[Job] = []
        for item in filtered_cards:
            desc, num_app, is_over, ago_txt = _fetch_detail(c, item["jid"])
            time.sleep(0.35)
            if not desc:
                continue

            # Confirma se a vaga é realmente remota (evita vagas presenciais com tag errada no LinkedIn)
            if not _is_truly_remote(item["title"], item["raw_loc"], desc):
                continue

            # Filtra vagas super concorridas (ex. "Over 200 applicants" ou > max_applicants)
            if max_applicants > 0 and num_app is not None:
                if is_over and num_app >= max_applicants:
                    continue
                if num_app > max_applicants:
                    continue

            app_badge = ""
            if item["early"] or (num_app is not None and num_app <= 25 and not is_over):
                app_badge = " | 🔥 Poucos candidatos"
            elif num_app is not None:
                prefix = "+" if is_over else "~"
                app_badge = f" | {prefix}{num_app} candidatos"

            ago_info = f" ({ago_txt})" if ago_txt else f" ({item['posted_at']})"
            jobs.append(
                Job(
                    title=item["title"],
                    url=item["url"],
                    location=f"{item['raw_loc']} | Remote{app_badge}{ago_info}",
                    description=desc,
                    posted_at=item["posted_at"],
                    remote=True,
                )
            )

    return jobs


def probe(slug: str) -> int:
    return 0
