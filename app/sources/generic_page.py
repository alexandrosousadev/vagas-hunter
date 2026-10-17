"""Página de carreiras própria (sem ATS conhecido): baixa o HTML e pede ao Ollama para listar as vagas.
Só funciona para páginas que trazem as vagas no HTML (não renderizadas por JavaScript)."""
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .. import llm
from .base import Job, client, html_to_text

SYSTEM = (
    "Você extrai vagas de emprego de páginas de carreiras. Responda só JSON no formato "
    '{"vagas": [{"titulo": str, "url": str, "local": str}]}. '
    "Use apenas links que aparecem na lista de links fornecida. Se não houver vagas, devolva {\"vagas\": []}."
)


def fetch(url: str) -> list[Job]:
    with client() as c:
        r = c.get(url)
        r.raise_for_status()
        page = r.text
    tree = HTMLParser(page)
    links = []
    for a in tree.css("a[href]"):
        text = a.text(strip=True)
        if text and len(text) < 150:
            links.append(f"- {text} -> {urljoin(url, a.attributes['href'])}")
    text = html_to_text(page)[:6000]
    user = f"URL: {url}\n\nTEXTO DA PÁGINA:\n{text}\n\nLINKS:\n" + "\n".join(links[:300])
    data = llm.chat_json(SYSTEM, user)
    valid = {urljoin(url, a.attributes["href"]) for a in tree.css("a[href]")}
    return [
        Job(title=v["titulo"], url=v["url"], location=v.get("local", ""))
        for v in data.get("vagas", [])
        if v.get("titulo") and v.get("url") in valid
    ]


def fetch_description(url: str) -> str:
    with client() as c:
        r = c.get(url)
        r.raise_for_status()
        return html_to_text(r.text)[:8000]
