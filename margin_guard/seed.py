"""Build the synthetic job shop: catalog, vendors, customers, open quotes and the vendor inbox.

Deterministic (fixed RNG seed + fixed AS_OF date), so the gold labels in
data/vendor_emails.json stay valid on every rebuild.

    python -m margin_guard.seed --reset
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from . import db
from .config import AS_OF, DB_PATH, EMAILS_PATH

VENDORS = [
    ("V-MWP", "Midwest Polymer Supply", "midwestpolymer.com"),
    ("V-GLE", "Great Lakes Elastomers", "glelastomers.com"),
    ("V-SUM", "Summit Silicones", "summitsilicones.com"),
    ("V-FLT", "FluoroTech Materials", "fluorotechmaterials.com"),
    ("V-RCB", "Ridgeline Carbon", "ridgelinecarbon.com"),
    ("V-BSS", "Buckeye Steel Service", "buckeyesteel.com"),
    ("V-KRD", "Keystone Rubber Distributors", "keystonerubber.com"),
]

# (id, name, category, cost_per_lb, aliases, [(vendor_id, is_primary)])
MATERIALS = [
    ("MAT-EPDM-50", "EPDM 50 Shore A compound", "elastomer", 1.95,
     ["EPDM 50", "EPDM-50", "EPDM50"], [("V-MWP", 1)]),
    ("MAT-EPDM-60", "EPDM 60 Shore A compound", "elastomer", 2.05,
     ["EPDM 60", "EPDM-60", "EPDM60"], [("V-MWP", 1)]),
    ("MAT-EPDM-70", "EPDM 70 Shore A compound", "elastomer", 2.10,
     ["EPDM 70", "EPDM-70", "EPDM70", "Black 70"], [("V-MWP", 1), ("V-KRD", 0)]),
    ("MAT-NBR-70", "Nitrile (NBR) 70 Shore A compound", "elastomer", 2.25,
     ["NBR 70", "Nitrile 70", "Buna-N 70", "Black 70"], [("V-GLE", 1), ("V-KRD", 0)]),
    ("MAT-NBR-90", "Nitrile (NBR) 90 Shore A compound", "elastomer", 2.48,
     ["NBR 90", "Nitrile 90", "Buna-N 90"], [("V-GLE", 1)]),
    ("MAT-SBR-60", "SBR 60 Shore A compound", "elastomer", 1.62,
     ["SBR 60", "SBR-60", "styrene butadiene 60"], [("V-MWP", 1)]),
    ("MAT-NR-40", "Natural rubber 40 Shore A compound", "elastomer", 1.88,
     ["NR 40", "natural rubber 40", "natural rubber"], [("V-MWP", 1)]),
    ("MAT-CR-60", "Neoprene (CR) 60 Shore A compound", "elastomer", 3.40,
     ["Neoprene 60", "CR 60", "polychloroprene 60", "neoprene"], [("V-GLE", 1)]),
    ("MAT-VMQ-50", "Silicone (VMQ) 50 Shore A compound", "elastomer", 5.10,
     ["silicone 50", "VMQ 50", "silicone"], [("V-SUM", 1)]),
    ("MAT-FKM-75", "Fluoroelastomer (FKM) 75 Shore A compound", "elastomer", 14.80,
     ["FKM 75", "Viton 75", "fluoroelastomer 75", "FKM"], [("V-FLT", 1)]),
    ("MAT-CB-N550", "Carbon black N550", "filler", 1.09,
     ["N550", "N-550", "carbon black N550", "carbon black"], [("V-RCB", 1)]),
    ("MAT-STL-1018", "1018 cold-rolled steel bar (inserts)", "metal", 0.84,
     ["1018", "1018 steel", "C1018 bar", "1018 cold rolled"], [("V-BSS", 1)]),
]

# Costs that changed before AS_OF: (material_id, cost_per_lb, effective_date).
# EPDM-60's Oct 1 increase was already applied, which is the trap behind email E13.
PRICE_HISTORY_OVERRIDES = {
    "MAT-EPDM-60": [(1.98, "2026-07-01"), (2.05, "2026-10-01")],
}

# (id, name, conversion_cost_per_unit, [(material_id, lb_per_unit, scrap_rate)])
PARTS = [
    ("P-1001", "EPDM door seal, 1.2 m", 1.35, [("MAT-EPDM-70", 0.42, 0.06)]),
    ("P-1002", "EPDM window gasket", 0.62, [("MAT-EPDM-60", 0.18, 0.05)]),
    ("P-1003", "EPDM grommet, 25 mm", 0.08, [("MAT-EPDM-50", 0.02, 0.08)]),
    ("P-1004", "EPDM HVAC duct boot", 2.10, [("MAT-EPDM-70", 1.10, 0.05), ("MAT-CB-N550", 0.12, 0.0)]),
    ("P-1005", "Nitrile O-ring kit (20 pc)", 0.95, [("MAT-NBR-70", 0.09, 0.10)]),
    ("P-1006", "Nitrile hydraulic seal, 60 mm", 0.70, [("MAT-NBR-90", 0.06, 0.08)]),
    ("P-1007", "Nitrile fuel hose sleeve", 1.80, [("MAT-NBR-70", 0.55, 0.05), ("MAT-CB-N550", 0.08, 0.0)]),
    ("P-1008", "Bonded engine mount", 4.60, [("MAT-NR-40", 0.85, 0.04), ("MAT-STL-1018", 1.40, 0.02)]),
    ("P-1009", "Natural rubber bumper pad", 0.55, [("MAT-NR-40", 0.30, 0.05)]),
    ("P-1010", "SBR floor mat, utility", 1.25, [("MAT-SBR-60", 2.40, 0.03)]),
    ("P-1011", "SBR splash guard", 1.10, [("MAT-SBR-60", 1.60, 0.04)]),
    ("P-1012", "Neoprene marine hatch seal", 1.90, [("MAT-CR-60", 0.65, 0.06)]),
    ("P-1013", "Neoprene vibration pad", 0.75, [("MAT-CR-60", 0.40, 0.04)]),
    ("P-1014", "Silicone medical tubing, 1 m", 2.40, [("MAT-VMQ-50", 0.22, 0.12)]),
    ("P-1015", "Silicone oven door gasket", 1.65, [("MAT-VMQ-50", 0.35, 0.08)]),
    ("P-1016", "FKM chemical pump diaphragm", 3.80, [("MAT-FKM-75", 0.28, 0.10)]),
    ("P-1017", "FKM valve seat", 1.20, [("MAT-FKM-75", 0.07, 0.10)]),
    ("P-1018", "Bonded EPDM bushing", 2.30, [("MAT-EPDM-70", 0.25, 0.05), ("MAT-STL-1018", 0.60, 0.02)]),
    ("P-1019", "EPDM roof flashing boot", 1.05, [("MAT-EPDM-60", 0.50, 0.05)]),
    ("P-1020", "Nitrile oil pan gasket", 0.85, [("MAT-NBR-70", 0.20, 0.07)]),
]

# (id, name, price_lock_until, contract_note)
CUSTOMERS = [
    ("C-01", "Lakeshore HVAC", None, None),
    ("C-02", "Prairie Ag Equipment", None, None),
    ("C-03", "Tri-County Plumbing Supply", None, None),
    ("C-04", "Ironbridge Trucks", "2026-12-31", "Annual supply agreement: quoted prices fixed through 2026-12-31."),
    ("C-05", "Cobalt Marine", None, None),
    ("C-06", "Redwood Medical Devices", "2027-03-31", "Validated-part agreement: price changes need 90 days notice; locked through 2027-03-31."),
    ("C-07", "Summit Pumps", None, None),
    ("C-08", "Granite Industrial", None, None),
    ("C-09", "Bluewater Filtration", None, None),
    ("C-10", "Northfield Appliance", None, None),
]

# Which parts each customer tends to buy, so quotes look like real accounts.
CUSTOMER_PARTS = {
    "C-01": ["P-1004", "P-1001", "P-1013"],
    "C-02": ["P-1009", "P-1010", "P-1008", "P-1007"],
    "C-03": ["P-1002", "P-1019", "P-1003", "P-1020"],
    "C-04": ["P-1008", "P-1018", "P-1007", "P-1020"],
    "C-05": ["P-1012", "P-1013", "P-1011"],
    "C-06": ["P-1014", "P-1015", "P-1017"],
    "C-07": ["P-1016", "P-1017", "P-1006", "P-1005"],
    "C-08": ["P-1006", "P-1005", "P-1018", "P-1010"],
    "C-09": ["P-1016", "P-1005", "P-1014"],
    "C-10": ["P-1015", "P-1002", "P-1001", "P-1003"],
}

N_OPEN_QUOTES = 45
N_CLOSED_QUOTES = 30
RNG_SEED = 42


def _cost_on(material_id: str, current: float, on: date) -> float:
    """Material cost per lb as it stood on a given date."""
    history = PRICE_HISTORY_OVERRIDES.get(material_id)
    if not history:
        return current
    cost = history[0][0]
    for value, eff in history:
        if date.fromisoformat(eff) <= on:
            cost = value
    return cost


def _price_change_key(material_id: str, cost_per_lb: float, effective: str) -> str:
    # Must match margin_guard.parser.price_change_key.
    return f"price_change:{material_id}:{cost_per_lb:.4f}:{effective}"


def _insert_quote(conn, rng, quote_id, customer_id, status, issued, valid_days, costs):
    valid_until = issued + timedelta(days=valid_days)
    target_margin = round(rng.uniform(0.22, 0.35), 3)
    margin_floor = rng.choice([0.18, 0.20])
    conn.execute(
        "INSERT INTO quotes VALUES (?, ?, ?, ?, ?, ?)",
        (quote_id, customer_id, status, issued.isoformat(), valid_until.isoformat(), margin_floor),
    )
    parts = rng.sample(CUSTOMER_PARTS[customer_id], k=rng.randint(1, min(3, len(CUSTOMER_PARTS[customer_id]))))
    part_index = {p[0]: p for p in PARTS}
    for part_id in parts:
        _, _, conversion, bom = part_index[part_id]
        material_cost = sum(
            lb * (1 + scrap) * _cost_on(mat, costs[mat], issued) for mat, lb, scrap in bom
        )
        unit_price = round((material_cost + conversion) / (1 - target_margin), 4)
        conn.execute(
            "INSERT INTO quote_lines (quote_id, part_id, qty, unit_price, material_cost_basis, conversion_cost)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (quote_id, part_id, rng.choice([250, 500, 1000, 2500, 5000]), unit_price,
             round(material_cost, 4), conversion),
        )


def build(conn, emails_path: Path = EMAILS_PATH) -> None:
    db.init_schema(conn)
    rng = random.Random(RNG_SEED)

    conn.executemany("INSERT INTO vendors VALUES (?, ?, ?)", VENDORS)
    costs = {}
    for mat_id, name, category, cost, aliases, vendors in MATERIALS:
        costs[mat_id] = cost
        conn.execute(
            "INSERT INTO materials VALUES (?, ?, ?, ?, ?)",
            (mat_id, name, category, cost, json.dumps(aliases)),
        )
        for vendor_id, primary in vendors:
            conn.execute("INSERT INTO material_vendors VALUES (?, ?, ?)", (mat_id, vendor_id, primary))

        primary_vendor = next(v for v, p in vendors if p)
        history = PRICE_HISTORY_OVERRIDES.get(mat_id, [(cost, "2026-07-01")])
        for value, eff in history:
            event_id = None
            if eff > "2026-07-01":
                # A change that arrived by email and was already applied.
                cur = conn.execute(
                    "INSERT INTO events (event_type, idempotency_key, source_ref, payload, status, created_at)"
                    " VALUES ('price_change.detected', ?, 'seed', ?, 'processed', ?)",
                    (
                        _price_change_key(mat_id, value, eff),
                        json.dumps({"material_id": mat_id, "vendor_id": primary_vendor,
                                    "new_cost_per_lb": value, "effective_date": eff}),
                        f"{eff} 08:00:00",
                    ),
                )
                event_id = cur.lastrowid
            conn.execute(
                "INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date, source_event_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (mat_id, primary_vendor, value, eff, event_id),
            )

    for part_id, name, conversion, bom in PARTS:
        conn.execute("INSERT INTO parts VALUES (?, ?, ?)", (part_id, name, conversion))
        for mat_id, lb, scrap in bom:
            conn.execute("INSERT INTO part_materials VALUES (?, ?, ?, ?)", (part_id, mat_id, lb, scrap))

    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", CUSTOMERS)
    customer_ids = [c[0] for c in CUSTOMERS]

    # Open quotes: issued in the six weeks before AS_OF and still valid.
    n = 0
    seq = 101
    while n < N_OPEN_QUOTES:
        issued = AS_OF - timedelta(days=rng.randint(1, 44))
        valid_days = rng.choice([30, 45, 60, 90])
        if issued + timedelta(days=valid_days) < AS_OF:
            continue
        _insert_quote(conn, rng, f"Q-2026-{seq:04d}", rng.choice(customer_ids), "open", issued, valid_days, costs)
        seq += 1
        n += 1

    # Closed history (won/lost) for later analysis.
    for _ in range(N_CLOSED_QUOTES):
        issued = date(2026, 4, 1) + timedelta(days=rng.randint(0, 120))
        status = rng.choice(["won", "won", "lost"])
        _insert_quote(conn, rng, f"Q-2026-{seq:04d}", rng.choice(customer_ids), status, issued, 30, costs)
        seq += 1

    emails = json.loads(Path(emails_path).read_text(encoding="utf-8"))
    for e in emails:
        conn.execute(
            "INSERT INTO inbox_emails (id, from_addr, subject, body, received_at) VALUES (?, ?, ?, ?, ?)",
            (e["id"], e["from"], e["subject"], e["body"], e["received_at"]),
        )
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="delete the existing database first")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    if args.db.exists():
        if not args.reset:
            raise SystemExit(f"{args.db} already exists; pass --reset to rebuild it")
        args.db.unlink()
    conn = db.connect(args.db)
    build(conn)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("materials", "parts", "customers", "quotes", "quote_lines", "inbox_emails")}
    open_q = conn.execute("SELECT COUNT(*) FROM quotes WHERE status = 'open'").fetchone()[0]
    print(f"Seeded {args.db}")
    print("  " + ", ".join(f"{k}={v}" for k, v in counts.items()) + f" (open quotes={open_q})")


if __name__ == "__main__":
    main()
