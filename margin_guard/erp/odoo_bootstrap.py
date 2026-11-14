"""Runs inside `odoo shell` (Odoo provides `env`), never imported by Margin Guard itself.

    python -m margin_guard.erp setup     # pipes this file in; you don't run it by hand

Step "install": a US company in USD, then the apps the connector reads and writes. The chart
of accounts follows the company's country, so the country is set before Invoicing installs.
Step "apikey": an API key for the admin user, printed once for the setup command to save.
Odoo 19 caps a key's life at three months; `setup --new-key` makes a fresh one.
"""
import datetime
import os

APPS = ["contacts", "sale_management", "sale_margin", "purchase", "stock", "mrp", "account"]
step = os.environ.get("MG_STEP", "install")

if step == "install":
    company = env.ref("base.main_company")  # noqa: F821  (env comes from odoo shell)
    company.write({
        "name": "Margin Guard demo shop (synthetic)",
        "country_id": env.ref("base.us").id,  # noqa: F821
        "currency_id": env.ref("base.USD").id,  # noqa: F821
    })
    env.cr.commit()  # noqa: F821
    todo = env["ir.module.module"].search([("name", "in", APPS), ("state", "!=", "installed")])  # noqa: F821
    if todo:
        todo.button_immediate_install()
    env.cr.commit()  # noqa: F821
    print("MG_INSTALLED=" + ",".join(sorted(APPS)))

elif step == "apikey":
    admin = env.ref("base.user_admin")  # noqa: F821
    expires = datetime.datetime.now() + datetime.timedelta(days=89)
    key = env["res.users.apikeys"].with_user(admin)._generate(None, "Margin Guard connector", expires)  # noqa: F821
    env.cr.commit()  # noqa: F821
    print("MG_API_KEY=" + key)
