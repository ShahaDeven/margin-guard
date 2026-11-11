"""Render docs/architecture.mmd to docs/architecture.png (needs Playwright + network for mermaid).

    python -m evals.render_diagram

The README embeds the PNG so the diagram shows in any Markdown viewer, not only
ones that draw Mermaid.
"""

import tempfile
from pathlib import Path

from margin_guard.config import ROOT

SRC = ROOT / "docs" / "architecture.mmd"
OUT = ROOT / "docs" / "architecture.png"


def main() -> None:
    from playwright.sync_api import sync_playwright

    code = SRC.read_text(encoding="utf-8")
    body = code.replace("<", "&lt;").replace(">", "&gt;").replace("&lt;br/&gt;", "<br/>")
    html = f"""<!doctype html><html><body style="background:#131416;margin:0;padding:28px">
<pre class="mermaid">{body}</pre>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: false, theme: 'dark', fontFamily: 'Segoe UI, Arial, sans-serif' }});
try {{ await mermaid.run(); document.body.dataset.ok = '1' }} catch (e) {{ document.body.dataset.err = String(e) }}
</script></body></html>"""
    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "diagram.html"
        page_file.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=2)
            page.goto(page_file.as_uri())
            page.wait_for_function("document.body.dataset.ok || document.body.dataset.err", timeout=60_000)
            err = page.evaluate("document.body.dataset.err")
            if err:
                raise SystemExit(f"mermaid could not render the diagram: {err}")
            page.locator("body").screenshot(path=str(OUT))
            browser.close()
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
