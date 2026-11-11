"""Build the attachment fixtures in data/attachments/ (synthetic supplier files).

    python -m evals.make_attachments

Needs openpyxl (in requirements.txt) and PyMuPDF (requirements-dev.txt). The files
are committed; this script only exists so they can be regenerated or extended.
Each one carries a trap the extraction eval checks (see vendor_emails_attachments.json).
"""

from pathlib import Path

from margin_guard.config import ROOT

OUT = ROOT / "data" / "attachments"


def gle_price_list(path: Path) -> None:
    """Great Lakes December list, $/kg, five grades: two of ours change, one of ours
    is unchanged, two are grades we don't buy."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "December 2026"
    ws.append(["Great Lakes Elastomers - Compound Price List"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Effective December 1, 2026. All prices USD per kg, FOB Toledo."])
    ws.append([])
    ws.append(["Grade", "Description", "Current (USD/kg)", "New (USD/kg)", "Change"])
    for c in ws[4]:
        c.font = Font(bold=True)
    for row in [
        ["NBR 70", "Nitrile 70 Shore A, black", 4.96, 5.20, "+4.8%"],
        ["NBR 90", "Nitrile 90 Shore A, black", 5.47, 5.47, "0.0%"],
        ["CR 60", "Neoprene 60 Shore A", 7.50, 7.95, "+6.0%"],
        ["HNBR 80", "Hydrogenated nitrile 80 Shore A", 18.40, 19.30, "+4.9%"],
        ["ECO 70", "Epichlorohydrin 70 Shore A", 11.20, 11.65, "+4.0%"],
    ]:
        ws.append(row)
    wb.save(path)


def buckeye_bar_pricing(path: Path) -> None:
    """Buckeye bar pricing, two sheets, $ per short ton; the date lives on the Read me sheet."""
    from openpyxl import Workbook

    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    readme.append(["Buckeye Steel Service - cold finished bar"])
    readme.append(["Prices are per short ton (2,000 lb), FOB Columbus."])
    readme.append(["Effective for releases from December 15, 2026."])
    prices = wb.create_sheet("Prices")
    prices.append(["Grade", "Size range", "Previous (USD/ton)", "New (USD/ton)"])
    for row in [
        ["1018 CR bar", '1/2" - 2"', 1680, 1820],
        ["1045 CR bar", '1/2" - 2"', 1790, 1940],
        ["12L14 CR bar", '1/2" - 2"', 2010, 2010],
    ]:
        prices.append(row)
    wb.save(path)


def ridgeline_letter(path: Path) -> None:
    """A one-page PDF price letter, per hundredweight, three grades, one of them ours."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        ("Ridgeline Carbon", 16),
        ("Price notice - carbon black", 12),
        ("", 11),
        ("Dear customer,", 11),
        ("", 11),
        ("Effective January 1, 2027, the following prices apply to all shipments:", 11),
        ("", 11),
        ("    N550    $121.00 per hundredweight (cwt)", 11),
        ("    N330    $126.50 per hundredweight (cwt)", 11),
        ("    N774    unchanged at $112.00 per hundredweight (cwt)", 11),
        ("", 11),
        ("Thank you for your business.", 11),
        ("Ridgeline Carbon customer service", 11),
    ]
    y = 72
    for text, size in lines:
        if text:
            page.insert_text((72, y), text, fontsize=size, fontname="helv")
        y += size + 9
    doc.save(path)


def summit_scan(path: Path) -> None:
    """A 'scanned' price sheet: drawn shapes only, no text layer."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(60, 60, 540, 120), color=(0.2, 0.2, 0.2), fill=(0.85, 0.85, 0.85))
    for i in range(12):
        y = 150 + i * 30
        page.draw_line((72, y), (520, y), color=(0.6, 0.6, 0.6))
        page.draw_rect(pymupdf.Rect(80, y + 6, 80 + 40 + (i * 37) % 260, y + 18), color=None, fill=(0.4, 0.4, 0.4))
    doc.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gle_price_list(OUT / "gle_price_list_dec2026.xlsx")
    buckeye_bar_pricing(OUT / "buckeye_bar_pricing_dec2026.xlsx")
    ridgeline_letter(OUT / "ridgeline_price_notice_jan2027.pdf")
    summit_scan(OUT / "summit_price_sheet_scan.pdf")
    for p in sorted(OUT.iterdir()):
        print(f"  wrote {p.relative_to(ROOT)} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
