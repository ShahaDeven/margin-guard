"""Build the attachment fixtures in data/attachments/ (synthetic supplier files).

    python -m evals.make_attachments

Needs openpyxl and Pillow (in requirements.txt) and PyMuPDF (requirements-dev.txt). The files
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


# ------------------------------------------------------------------ scans for OCR (Pillow only)


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)          # Pillow 10.1+, needs FreeType
    except TypeError:
        return ImageFont.truetype("arial.ttf", size)


def _degrade(img, angle: float, blur: float, noise: int, seed: int):
    """What a fax or a phone does to a clean page: a tilt, softness, speckle."""
    import random

    from PIL import Image, ImageFilter
    rnd = random.Random(seed)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255 if img.mode == "L" else (238, 233, 222))
    img = img.filter(ImageFilter.GaussianBlur(blur))
    px = img.load()
    w, h = img.size
    for _ in range(noise):
        x, y = rnd.randrange(w), rnd.randrange(h)
        px[x, y] = 0 if img.mode == "L" else (60, 60, 60)
    return img


def midwest_fax(path: Path) -> None:
    """A faxed price sheet, image only (no text layer), $/lb: three of ours change, one of
    ours is unchanged, one grade we don't buy."""
    from PIL import Image, ImageDraw

    img = Image.new("L", (1700, 2200), 255)                # US letter at 200 dpi
    d = ImageDraw.Draw(img)
    d.text((150, 140), "MIDWEST POLYMER SUPPLY", font=_font(54), fill=0)
    d.text((150, 215), "Compound price sheet  -  page 1 of 1", font=_font(34), fill=0)
    d.text((150, 330), "Effective for shipments on or after January 1, 2027.", font=_font(34), fill=0)
    d.text((150, 380), "All prices in USD per pound, FOB Des Plaines, IL.", font=_font(34), fill=0)
    rows = [("Grade", "Current $/lb", "New $/lb"),
            ("EPDM 50", "1.95", "2.04"),
            ("EPDM 60", "2.05", "2.15"),
            ("EPDM 80", "2.31", "2.42"),
            ("SBR 60", "1.62", "1.62"),
            ("NR 40", "1.88", "1.97")]
    y = 520
    for i, (a, b, c) in enumerate(rows):
        f = _font(38)
        d.text((170, y), a, font=f, fill=0)
        d.text((720, y), b, font=f, fill=0)
        d.text((1130, y), c, font=f, fill=0)
        if i == 0:
            d.line((150, y + 58, 1500, y + 58), fill=0, width=3)
        y += 92
    d.text((150, y + 80), "Questions: call your Midwest Polymer account rep.", font=_font(32), fill=0)
    d.text((1180, 2080), "FAX  11/02/2026 08:14", font=_font(26), fill=0)
    img = _degrade(img, angle=0.7, blur=0.9, noise=2500, seed=7)
    img.save(path, "PDF", resolution=200)


def fluorotech_photo(path: Path) -> None:
    """A phone photo of a printed letter, per kg: FKM 75 goes up from February."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1600, 1200), (238, 233, 222))   # paper under warm light
    d = ImageDraw.Draw(img)
    ink = (40, 40, 46)
    d.text((110, 90), "FluoroTech Materials", font=_font(56), fill=ink)
    d.text((110, 220), "To our customers,", font=_font(38), fill=ink)
    d.text((110, 300), "Due to higher monomer costs, the price of FKM 75", font=_font(38), fill=ink)
    d.text((110, 360), "fluoroelastomer compound changes from $32.63/kg", font=_font(38), fill=ink)
    d.text((110, 420), "to $33.50/kg, effective February 1, 2027.", font=_font(38), fill=ink)
    d.text((110, 520), "Orders placed before that date ship at the current price.", font=_font(38), fill=ink)
    d.text((110, 640), "Sincerely,", font=_font(38), fill=ink)
    d.text((110, 700), "Dana Whitfield, FluoroTech Materials", font=_font(38), fill=ink)
    shade = Image.linear_gradient("L").resize(img.size).point(lambda v: 255 - v // 5)
    img = Image.composite(img, Image.new("RGB", img.size, (205, 198, 186)), shade)    # light falls off to one side
    img = _degrade(img, angle=-1.8, blur=1.1, noise=0, seed=3)
    img.save(path, "JPEG", quality=72)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gle_price_list(OUT / "gle_price_list_dec2026.xlsx")
    buckeye_bar_pricing(OUT / "buckeye_bar_pricing_dec2026.xlsx")
    ridgeline_letter(OUT / "ridgeline_price_notice_jan2027.pdf")
    summit_scan(OUT / "summit_price_sheet_scan.pdf")
    midwest_fax(OUT / "midwest_price_sheet_fax_jan2027.pdf")
    fluorotech_photo(OUT / "fluorotech_letter_photo.jpg")
    for p in sorted(OUT.iterdir()):
        print(f"  wrote {p.relative_to(ROOT)} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
