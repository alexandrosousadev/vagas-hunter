import html
import re
from dataclasses import dataclass

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..config import CFG

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class Job:
    title: str
    url: str
    location: str = ""
    description: str = ""
    posted_at: str = ""
    remote: bool | None = None   # quando o ATS informa explicitamente


def client() -> httpx.Client:
    timeout = CFG.get("coleta", {}).get("timeout_segundos", 25)
    return httpx.Client(
        headers={
            "User-Agent": UA,
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        timeout=timeout,
        follow_redirects=True,
    )


def html_to_text(raw: str) -> str:
    """Converte HTML (às vezes escapado, como no Greenhouse) em texto limpo."""
    if not raw:
        return ""
    raw = html.unescape(raw)
    tree = HTMLParser(raw)
    for tag in tree.css("script, style"):
        tag.decompose()
    text = tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()
