"""OCR for scanned price sheets: Tesseract, run as a program, with per-word confidence.

A scanned PDF or a phone photo of a price letter has no text to read. Tesseract turns
the image into text, and says how sure it is of every word. Margin Guard keeps both:

    the text            goes to the extractor like any other attachment
    mean confidence     an image whose words average under MIN_MEAN is noise, not a reading,
                        and is treated as unreadable (a person reads the original)
    uncertain numbers   any word with a digit read under SURE is listed, because a misread
                        price ("2.O4", "1.37" for "1.97") is the mistake that costs money

Every price read this way is shown to a person before it moves a quote (see parser.py):
OCR makes a scan usable, it does not make it trusted.

Tesseract is found at MG_TESSERACT, on PATH, or in its default Windows install folder.
Without it, a scan is unreadable, as before.
"""

import csv
import io
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MIN_MEAN = 60          # mean word confidence (0-100) below this: not a reading
SURE = 80              # a number read below this confidence is listed as uncertain
MIN_WIDTH = 1800       # small images are scaled up first; Tesseract wants ~10 px tall letters
TIMEOUT = 90           # seconds per page

_WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass
class Reading:
    text: str
    words: int = 0
    mean_confidence: float = 0.0
    uncertain: list[str] = field(default_factory=list)


def tesseract() -> str | None:
    """The Tesseract program, or None if it isn't installed."""
    explicit = os.getenv("MG_TESSERACT")
    if explicit:
        return explicit if Path(explicit).exists() else None
    found = shutil.which("tesseract")
    if found:
        return found
    return str(_WINDOWS_DEFAULT) if _WINDOWS_DEFAULT.exists() else None


def _prepare(img):
    """Grey, large enough to read, and despeckled. A 3-pixel median filter removes the dots a
    fax or a dusty scanner leaves, which otherwise read as decimal points ("1.62" became
    "4.62" on the demo fax). Thresholding is left to Tesseract, which does it better."""
    from PIL import Image, ImageFilter, ImageOps

    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < MIN_WIDTH:
        scale = MIN_WIDTH / img.width
        img = img.resize((MIN_WIDTH, round(img.height * scale)), Image.LANCZOS)
    return img.filter(ImageFilter.MedianFilter(3))


def _tsv(exe: str, img) -> list[dict]:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    # --psm 4: a single column of text of variable sizes, which keeps a price row on one line.
    out = subprocess.run([exe, "stdin", "stdout", "-l", "eng", "--psm", "4", "--dpi", "300", "tsv"],
                         input=buf.getvalue(), capture_output=True, timeout=TIMEOUT, check=True)
    rows = csv.DictReader(io.StringIO(out.stdout.decode("utf-8", errors="replace")), delimiter="\t",
                          quoting=csv.QUOTE_NONE)
    return [r for r in rows if r.get("level") == "5" and (r.get("text") or "").strip()]


def read_images(images: list) -> Reading:
    """Text from page images, one block per page, with how sure Tesseract was."""
    exe = tesseract()
    if exe is None:
        raise FileNotFoundError("Tesseract is not installed")
    pages, confs, uncertain = [], [], []
    for img in images:
        words = _tsv(exe, _prepare(img))
        lines: dict[tuple, list[str]] = {}
        for w in words:
            lines.setdefault((int(w["block_num"]), int(w["par_num"]), int(w["line_num"])), []).append(w["text"])
            conf = float(w["conf"])
            confs.append(conf)
            if conf < SURE and any(ch.isdigit() for ch in w["text"]) and w["text"] not in uncertain:
                uncertain.append(w["text"])
        pages.append("\n".join(" ".join(ws) for _, ws in sorted(lines.items())))
    text = "\n\n".join(f"[page {i}, read by OCR]\n{t}" for i, t in enumerate(pages, start=1) if t.strip())
    mean = sum(confs) / len(confs) if confs else 0.0
    return Reading(text, len(confs), round(mean, 1), uncertain)


def pdf_images(reader) -> list:
    """The scanned image on each page of a PDF (the largest one, if a page has several)."""
    out = []
    for page in reader.pages:
        imgs = [i.image for i in page.images if i.image is not None]
        if imgs:
            out.append(max(imgs, key=lambda im: im.width * im.height))
    return out
