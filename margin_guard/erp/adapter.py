"""The boundary every ERP adapter implements. The sync engine (sync.py) only ever sees these
records, in Margin Guard's own terms: pounds, dollars per pound, its own ids. An adapter does
the ERP-specific work (units of measure, currencies, price breaks, how a quote's state is
spelled) and reports anything it can't map instead of guessing.

Each `pull(kind, since)` returns the records changed at or after `since` (an ERP timestamp,
or None for everything), oldest first. Every record carries:

    erp_id       the ERP's own id, stable for the life of the record
    write_date   when the ERP last changed it; the next cursor is the largest one seen

and the fields below. `ref` fields are the natural keys Margin Guard uses (V-MWP, MAT-EPDM-70,
Q-2026-0101); a record without one gets an id made from the ERP id.
"""

from typing import Protocol

# Pulled in this order, so every record's references exist by the time it arrives.
KINDS = ("supplier", "customer", "material", "part", "supplier_price", "bom", "quote", "bill_line")

FIELDS = {
    "supplier": "ref, name, email_domain",
    "customer": "ref, name, tier ('key' | 'standard'), price_lock_until, contract_note, buyer_name, "
                "buyer_email, buyer_phone, account_manager, account_manager_phone",
    "material": "ref, name, cost_per_lb",
    "part": "ref, name",
    "supplier_price": "material_ref, supplier_ref, cost_per_lb, effective_date, is_costing",
    "bom": "part_ref, lines: [(material_ref, gross lb per unit)]",
    "quote": "ref, customer_ref, status ('open' | 'won' | 'lost'), issued_date, valid_until, ordered_date, "
             "lines: [{erp_id, part_ref, qty, unit_price, cost_each}]",
    "bill_line": "invoice_no, line_no, invoice_date, supplier_ref, item, qty, unit ('lb' ...), unit_price",
}


class ErpAdapter(Protocol):
    system: str                                   # "odoo"; keys the link and cursor tables

    def pull(self, kind: str, since: str | None) -> list[dict]:
        """Records of `kind` changed at or after `since`, oldest first."""
        ...

    def skipped(self) -> list[str]:
        """What the last pulls could not map (a currency, a unit), in plain words."""
        ...
