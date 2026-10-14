"""Build a fully processed shop: seed it, read the inbox from cached extractions, run the coordinator.

Extraction is replayed from evals/results/extractions.json (the inbox is the same in
every shop), so only the judgment calls reach the decider.
"""

import contextlib
import io
import json
from pathlib import Path

from margin_guard import coordinator, ingest, seed
from margin_guard.decide import Decider
from margin_guard.parser import EmailExtraction

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
EXTRACTIONS = RESULTS_DIR / "extractions.json"


def build_processed_shop(conn, rng_seed: int, decider: Decider, quiet: bool = True) -> None:
    if not EXTRACTIONS.exists():
        raise SystemExit("Run `python -m evals.eval_extraction` first to cache extractions.")
    extractions = json.loads(EXTRACTIONS.read_text(encoding="utf-8"))
    seed.build(conn, rng_seed=rng_seed)
    out = io.StringIO() if quiet else None
    with contextlib.redirect_stdout(out) if quiet else contextlib.nullcontext():
        ingest.run(conn, extract=lambda e: EmailExtraction.model_validate(extractions[e["id"]]))
        coordinator.run(conn, decider)
