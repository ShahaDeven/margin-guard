"""A small client for Odoo 19's external JSON-2 API.

    POST {url}/json/2/{model}/{method}
    Authorization: bearer {api key}
    X-Odoo-Database: {database}
    body: the method's keyword arguments as JSON ("ids", "domain", "vals_list", "context", ...)

JSON-2 replaces XML-RPC/JSON-RPC (which Odoo has scheduled for removal), and needs only an API
key: no user id, no password. Odoo's hosted Standard and free plans don't allow external API
access at all, which is why the demo runs a self-hosted Community in Docker.

Reads retry on a dropped connection or a 5xx; writes never retry, because a create that
reached the server before the connection dropped would be made twice.
"""

import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import ROOT

KEY_FILE = ROOT / ".odoo" / "api_key"
READS = {"search", "search_read", "read", "search_count", "fields_get", "name_search"}


class OdooError(RuntimeError):
    """Odoo refused a call; the message is Odoo's own."""


def settings() -> tuple[str, str, str | None]:
    """(url, database, api key). The key comes from MG_ODOO_KEY or the file setup wrote."""
    key = os.getenv("MG_ODOO_KEY") or (KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else None)
    return (os.getenv("MG_ODOO_URL", "http://localhost:8069").rstrip("/"),
            os.getenv("MG_ODOO_DB", "margin_guard"), key)


class OdooClient:
    def __init__(self, url: str | None = None, db: str | None = None, key: str | None = None,
                 timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        u, d, k = settings()
        self.url, self.db, self.key = url or u, db or d, key or k
        if not self.key:
            raise OdooError(f"no Odoo API key: run `python -m margin_guard.erp setup`, or set MG_ODOO_KEY")
        self.http = httpx.Client(timeout=timeout, transport=transport, headers={
            "Authorization": f"bearer {self.key}",
            "X-Odoo-Database": self.db,
            "Content-Type": "application/json",
            "User-Agent": "margin-guard-connector",
        })

    def call(self, model: str, method: str, **kwargs: Any) -> Any:
        attempts = 3 if method in READS else 1
        for attempt in range(attempts):
            try:
                r = self.http.post(f"{self.url}/json/2/{model}/{method}", json=kwargs)
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise OdooError(f"Odoo at {self.url} is unreachable: {exc}") from exc
            if r.status_code >= 500 and attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise OdooError(f"{model}.{method}: {_message(r)}")
            return r.json() if r.content else None
        raise OdooError(f"{model}.{method}: no response")  # pragma: no cover

    # The handful of ORM calls the connector uses, so callers read like Odoo code.
    def search_read(self, model: str, domain: list, fields: list[str], **kw: Any) -> list[dict]:
        return self.call(model, "search_read", domain=domain, fields=fields, **kw)

    def create(self, model: str, vals_list: list[dict], context: dict | None = None) -> list[int]:
        ids = self.call(model, "create", vals_list=vals_list, **({"context": context} if context else {}))
        return ids if isinstance(ids, list) else [ids]

    def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return self.call(model, "write", ids=ids, vals=vals)

    def xmlid(self, module: str, name: str) -> int:
        """The database id behind an XML id like uom.product_uom_lb."""
        rows = self.search_read("ir.model.data", [["module", "=", module], ["name", "=", name]], ["res_id"], limit=1)
        if not rows:
            raise OdooError(f"no record {module}.{name}")
        return rows[0]["res_id"]


def _message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    return f"HTTP {r.status_code}: {body.get('message') or body.get('name') or body}"


def ensure_key_dir() -> Path:
    KEY_FILE.parent.mkdir(exist_ok=True)
    return KEY_FILE
