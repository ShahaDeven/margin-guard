"""Resolve the names vendors use for materials to catalog IDs.

Matching is deterministic: normalized alias lookup first, then fuzzy matching.
When the sending vendor is known, candidates are narrowed to the materials that
vendor supplies. Anything that is still ambiguous goes to a person rather than
being guessed.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Words that carry no identity ("EPDM 70 duro compound" == "EPDM 70").
_STOPWORDS = {"compound", "duro", "durometer", "shore", "a", "grade", "our", "the", "equivalent"}

FUZZY_ACCEPT = 0.85
FUZZY_MARGIN = 0.08      # best match must beat the runner-up by this much


@dataclass
class MatchResult:
    material_id: str | None
    method: str                          # exact | contains | fuzzy | ambiguous | none
    candidates: list[str] = field(default_factory=list)
    score: float = 0.0


def normalize_name(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    # Glue letter-number splits so "EPDM70" and "EPDM 70" agree.
    text = re.sub(r"([a-z])\s*(\d)", r"\1 \2", text)
    return " ".join(w for w in text.split() if w not in _STOPWORDS)


def _load_names(conn: sqlite3.Connection) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for row in conn.execute("SELECT id, name, aliases FROM materials"):
        names[row["id"]] = [normalize_name(row["name"])] + [
            normalize_name(a) for a in json.loads(row["aliases"])
        ]
    return names


def vendor_materials(conn: sqlite3.Connection, vendor_id: str) -> set[str]:
    rows = conn.execute("SELECT material_id FROM material_vendors WHERE vendor_id = ?", (vendor_id,))
    return {r["material_id"] for r in rows}


def resolve_material(conn: sqlite3.Connection, text: str, vendor_id: str | None = None) -> MatchResult:
    query = normalize_name(text)
    if not query:
        return MatchResult(None, "none")

    names = _load_names(conn)
    if vendor_id:
        supplied = vendor_materials(conn, vendor_id)
        if supplied:
            names = {m: n for m, n in names.items() if m in supplied}

    exact = sorted(m for m, aliases in names.items() if query in aliases)
    if len(exact) == 1:
        return MatchResult(exact[0], "exact", exact, 1.0)
    if len(exact) > 1:
        return MatchResult(None, "ambiguous", exact, 1.0)

    # Containment: every token of an alias appears in the query
    # ("c 1018 cold rolled bar" contains "1018"). The most specific alias wins.
    q_tokens = set(query.split())
    contained: dict[str, int] = {}
    for m, aliases in names.items():
        sizes = [len(a.split()) for a in aliases if a and set(a.split()) <= q_tokens]
        if sizes:
            contained[m] = max(sizes)
    if contained:
        top = max(contained.values())
        best = sorted(m for m, size in contained.items() if size == top)
        if len(best) == 1:
            return MatchResult(best[0], "contains", best, 0.95)
        return MatchResult(None, "ambiguous", best, 0.95)

    scored = sorted(
        ((max(SequenceMatcher(None, query, a).ratio() for a in aliases), m) for m, aliases in names.items()),
        reverse=True,
    )
    if not scored or scored[0][0] < FUZZY_ACCEPT:
        return MatchResult(None, "none", [m for _, m in scored[:3]], scored[0][0] if scored else 0.0)

    best_score, best = scored[0]
    close = [m for s, m in scored if best_score - s < FUZZY_MARGIN]
    if len(close) > 1:
        return MatchResult(None, "ambiguous", close, best_score)
    return MatchResult(best, "fuzzy", [best], best_score)
