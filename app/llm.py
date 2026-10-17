"""Cliente unificado de IA: suporta Ollama (local), Google Gemini (nuvem grátis) e Groq (nuvem grátis).

Para trocar quando for subir para a web, basta mudar `ia.provedor` em `config.yaml`
ou definir a variável de ambiente `LLM_PROVIDER=gemini` (ou `groq`) + `GEMINI_API_KEY` / `GROQ_API_KEY`.
"""
import hashlib
import json
import math
import os
import re

import httpx

from .config import CFG

_O = CFG.get("ollama", {})
_IA = CFG.get("ia", {})

PROVIDER = (os.getenv("LLM_PROVIDER") or _IA.get("provedor") or "ollama").lower()

# Ollama
OLLAMA_URL = os.getenv("OLLAMA_URL") or _O.get("url", "http://localhost:11434")
OLLAMA_CHAT = _O.get("modelo_chat", "qwen2.5:7b")
OLLAMA_EMBED = _O.get("modelo_embed", "nomic-embed-text")

# Gemini (Google AI Studio - plano gratuito)
GEMINI_KEY = os.getenv("GEMINI_API_KEY") or _IA.get("gemini_api_key", "")
GEMINI_CHAT = _IA.get("gemini_modelo_chat", "gemini-2.5-flash")
GEMINI_EMBED = _IA.get("gemini_modelo_embed", "text-embedding-004")

# Groq (plano gratuito)
GROQ_KEY = os.getenv("GROQ_API_KEY") or _IA.get("groq_api_key", "")
GROQ_CHAT = _IA.get("groq_modelo_chat", "llama-3.3-70b-versatile")


def _clean_json(txt: str) -> dict:
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    return json.loads(txt)


def chat_json(system: str, user: str, timeout: float = 300) -> dict:
    """Pede uma resposta em JSON ao provedor configurado (ollama | gemini | groq)."""
    if PROVIDER == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_CHAT}:generateContent"
        r = httpx.post(
            url,
            params={"key": GEMINI_KEY},
            timeout=60,
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            },
        )
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _clean_json(text)

    if PROVIDER == "groq":
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            timeout=60,
            json={
                "model": GROQ_CHAT,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        r.raise_for_status()
        return _clean_json(r.json()["choices"][0]["message"]["content"])

    # Padrão: Ollama local
    r = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        timeout=timeout,
        json={
            "model": OLLAMA_CHAT,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 8192},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
    )
    r.raise_for_status()
    return _clean_json(r.json()["message"]["content"])


def _hash_embed(text: str, dim: int = 256) -> list[float]:
    """Fallback leve de embedding local (feature hashing) caso use Groq na nuvem sem chave Gemini."""
    vec = [0.0] * dim
    for tok in re.findall(r"[a-z0-9+#.]{2,}", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embed(texts: list[str], kind: str = "document") -> list[list[float]]:
    """Gera embeddings usando Ollama, Gemini (nuvem) ou fallback leve."""
    if PROVIDER == "gemini" or (PROVIDER == "groq" and GEMINI_KEY):
        task_type = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_EMBED}:batchEmbedContents"
        reqs = [
            {
                "model": f"models/{GEMINI_EMBED}",
                "content": {"parts": [{"text": (t or " ")[:5000]}]},
                "taskType": task_type,
            }
            for t in texts
        ]
        r = httpx.post(url, params={"key": GEMINI_KEY}, timeout=60, json={"requests": reqs})
        r.raise_for_status()
        return [item["values"] for item in r.json()["embeddings"]]

    if PROVIDER == "groq":
        return [_hash_embed(t) for t in texts]

    # Padrão: Ollama local (nomic-embed-text)
    prefix = "search_query: " if kind == "query" else "search_document: "
    r = httpx.post(
        f"{OLLAMA_URL}/api/embed",
        timeout=300,
        json={
            "model": OLLAMA_EMBED,
            "input": [prefix + t[:6000] for t in texts],
        },
    )
    r.raise_for_status()
    return r.json()["embeddings"]


def available() -> bool:
    if PROVIDER == "gemini":
        return bool(GEMINI_KEY)
    if PROVIDER == "groq":
        return bool(GROQ_KEY)
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False
