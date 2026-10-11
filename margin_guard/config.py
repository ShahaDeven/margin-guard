import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("MG_DB_PATH", ROOT / "data" / "margin_guard.db"))
EMAILS_PATH = ROOT / "data" / "vendor_emails.json"

MODEL = os.getenv("MG_MODEL", "claude-sonnet-5-5")
USE_FALLBACKS = os.getenv("MG_FALLBACKS", "1") == "1"

# The demo shop lives on a fixed calendar so quotes, validity windows and
# effective dates line up the same way on every run.
AS_OF = date.fromisoformat(os.getenv("MG_AS_OF", "2026-10-15"))

# Normalization guardrails
SANITY_MAX_CHANGE = 0.30       # a >30% move is more likely a unit error than a real price change
MIN_EXTRACTION_CONFIDENCE = 0.7
