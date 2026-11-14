"""The ERP connector's command line.

    python -m margin_guard.erp setup [--new-key]   # local Odoo in Docker, apps, API key, demo shop
    python -m margin_guard.erp load                # load the demo shop into a running Odoo
    python -m margin_guard.erp status              # is Odoo reachable, and what is in it

`setup` is safe to run again: each step checks whether it has already been done.
"""

import argparse
import os
import subprocess
import sys
import time

import httpx

from ..config import ROOT
from .odoo import KEY_FILE, OdooClient, OdooError, ensure_key_dir, settings
from .odoo_seed import already_loaded, load

COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.odoo.yml")]
BOOTSTRAP = ROOT / "margin_guard" / "erp" / "odoo_bootstrap.py"


def _run(args: list[str], *, stdin: str | None = None, env_step: str | None = None) -> str:
    cmd = COMPOSE + args
    if env_step:
        cmd = COMPOSE + ["run", "--rm", "-T", "-e", f"MG_STEP={env_step}", "odoo", "odoo", "shell", "-d", _db(), "--no-http"]
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd)}\n{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout


def _db() -> str:
    return settings()[1]


def _wait_http(url: str, seconds: int = 300) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if httpx.get(f"{url}/web/login", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(3)
    sys.exit(f"Odoo did not answer at {url} within {seconds}s")


def setup(new_key: bool) -> None:
    url, dbname, _ = settings()
    print("1/5 Postgres")
    _run(["up", "-d", "--wait", "db"])
    have_db = _run(["exec", "-T", "db", "psql", "-U", "odoo", "-d", "postgres", "-tAc",
                    f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'"]).strip() == "1"
    if not have_db:
        print(f"2/5 Creating database {dbname} (a few minutes the first time)")
        _run(["run", "--rm", "odoo", "--", "-d", dbname, "-i", "base", "--stop-after-init"])
    else:
        print(f"2/5 Database {dbname} exists")
    print("3/5 Company and apps (Sales, Sales margin, Purchase, Inventory, Manufacturing, Invoicing)")
    _run(["stop", "odoo"])
    out = _run([], stdin=BOOTSTRAP.read_text(encoding="utf-8"), env_step="install")
    print("    " + next((ln for ln in out.splitlines() if ln.startswith("MG_INSTALLED=")), "installed"))
    if new_key or not KEY_FILE.exists():
        print("4/5 API key")
        out = _run([], stdin=BOOTSTRAP.read_text(encoding="utf-8"), env_step="apikey")
        key = next((ln[len("MG_API_KEY="):] for ln in out.splitlines() if ln.startswith("MG_API_KEY=")), None)
        if not key:
            sys.exit("Odoo did not return an API key")
        ensure_key_dir().write_text(key, encoding="utf-8")
        print(f"    saved to {KEY_FILE.relative_to(ROOT)} (git-ignored; Odoo keys last up to 3 months)")
    else:
        print(f"4/5 API key on file ({KEY_FILE.relative_to(ROOT)})")
    _run(["up", "-d", "odoo"])
    _wait_http(url)
    print("5/5 Demo shop")
    load(OdooClient())
    print(f"\nOdoo is at {url}  (login admin / admin; local demo only)")


def status() -> None:
    url, dbname, key = settings()
    try:
        c = OdooClient()
        n = {label: c.call(m, "search_count", domain=d) for label, m, d in [
            ("suppliers", "res.partner", [["supplier_rank", ">", 0]]),
            ("customers", "res.partner", [["customer_rank", ">", 0]]),
            ("products", "product.product", []), ("supplier prices", "product.supplierinfo", []),
            ("BOMs", "mrp.bom", []), ("open quotes", "sale.order", [["state", "in", ["draft", "sent"]]]),
            ("confirmed orders", "sale.order", [["state", "=", "sale"]]),
            ("vendor bills", "account.move", [["move_type", "=", "in_invoice"]])]}
    except OdooError as exc:
        sys.exit(str(exc))
    print(f"Odoo {url}, database {dbname}: reachable, demo shop {'loaded' if already_loaded(c) else 'not loaded'}")
    print("  " + ", ".join(f"{k} {v}" for k, v in n.items()))


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m margin_guard.erp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="local Odoo in Docker with the demo shop")
    s.add_argument("--new-key", action="store_true", help="make a fresh API key")
    sub.add_parser("load", help="load the demo shop into a running Odoo")
    sub.add_parser("status", help="check the connection")
    args = ap.parse_args()
    os.chdir(ROOT)
    if args.cmd == "setup":
        setup(args.new_key)
    elif args.cmd == "load":
        load(OdooClient())
    else:
        status()


if __name__ == "__main__":
    main()
