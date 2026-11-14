"""ERP connector: Margin Guard reads a shop's suppliers, materials, BOMs, quotes and vendor
bills from an ERP, and writes back only what a person approved. The first adapter is Odoo 19
Community over its JSON-2 API (odoo.py); `python -m margin_guard.erp setup` runs one locally."""
