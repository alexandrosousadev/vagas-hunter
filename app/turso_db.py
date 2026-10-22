"""Cliente Turso compatível com sqlite3.Connection e sqlite3.Row."""
import json
import os
import re
import httpx

TURSO_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()


def is_turso_enabled() -> bool:
    return bool(TURSO_URL and TURSO_TOKEN)


def _http_url(url: str) -> str:
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):] + "/v2/pipeline"
    if url.startswith("https://"):
        return url if url.endswith("/v2/pipeline") else url.rstrip("/") + "/v2/pipeline"
    return "https://" + url.lstrip("/") + "/v2/pipeline"


def _format_args(args):
    if not args:
        return []
    params = []
    for a in args:
        if a is None:
            params.append({"type": "null"})
        elif isinstance(a, bool):
            params.append({"type": "integer", "value": "1" if a else "0"})
        elif isinstance(a, int):
            params.append({"type": "integer", "value": str(a)})
        elif isinstance(a, float):
            params.append({"type": "float", "value": a})
        elif isinstance(a, (dict, list)):
            params.append({"type": "text", "value": json.dumps(a, ensure_ascii=False)})
        else:
            params.append({"type": "text", "value": str(a)})
    return params


class TursoRow(dict):
    """Simula sqlite3.Row permitindo acesso por índice [0] ou chave ['title']."""
    def __init__(self, cols, vals):
        self._cols = cols
        self._vals = vals
        super().__init__(zip(cols, vals))

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._vals[item]
        return super().__getitem__(item)

    def keys(self):
        return self._cols


class TursoCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self._idx = 0
        self.rowcount = -1
        self.lastrowid = None

    def execute(self, sql: str, args=None):
        return self.conn.execute(sql, args)

    def executemany(self, sql: str, seq_of_args):
        for args in seq_of_args:
            self.execute(sql, args)
        return self

    def fetchone(self):
        if self._idx < len(self._rows):
            r = self._rows[self._idx]
            self._idx += 1
            return r
        return None

    def fetchall(self):
        if self._idx == 0:
            res = self._rows
            self._idx = len(self._rows)
            return res
        res = self._rows[self._idx:]
        self._idx = len(self._rows)
        return res


class TursoConnection:
    def __init__(self, url: str, token: str):
        self.endpoint = _http_url(url)
        self.token = token
        self._http = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {token}"})

    def _convert_val(self, v):
        if not isinstance(v, dict):
            return v
        t = v.get("type")
        val = v.get("value")
        if t == "null":
            return None
        if t == "integer":
            return int(val)
        if t == "float":
            return float(val)
        return val

    def execute(self, sql: str, args=None) -> TursoCursor:
        stmt = {"sql": sql}
        if args:
            stmt["args"] = _format_args(args)
        r = self._http.post(self.endpoint, json={"requests": [{"type": "execute", "stmt": stmt}]})
        if r.status_code != 200:
            raise RuntimeError(f"Turso HTTP error {r.status_code}: {r.text[:200]}")
        data = r.json()
        results = data.get("results") or []
        if not results:
            cur = TursoCursor(self)
            return cur
        first = results[0]
        if first.get("type") == "error":
            raise RuntimeError(first.get("error", {}).get("message", "Unknown Turso error"))
        resp = first.get("response", {}).get("result", {})
        cols = [c["name"] for c in resp.get("cols", [])]
        raw_rows = resp.get("rows", [])
        parsed_rows = []
        for raw in raw_rows:
            vals = [self._convert_val(c) for c in raw]
            parsed_rows.append(TursoRow(cols, vals))
        cur = TursoCursor(self)
        cur._rows = parsed_rows
        cur.rowcount = resp.get("affected_row_count", -1)
        cur.lastrowid = resp.get("last_insert_rowid")
        return cur

    def executescript(self, script: str):
        for stmt in script.strip().split(";"):
            s = stmt.strip()
            if s:
                self.execute(s)

    def commit(self):
        # O Turso em modo pipeline HTTP autocommit em cada request
        pass

    def close(self):
        self._http.close()
