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


def costing_vendor(conn: sqlite3.Connection, material_id: str) -> str | None:
    """The supplier whose price a material is costed at (material_vendors.is_primary).

    A shop can buy one material from several suppliers, but quotes are costed at
    one price. Only this supplier's changes move margins; another supplier's
    price is recorded as an alternative. None if no supplier is marked primary.
    """
    row = conn.execute(
        "SELECT vendor_id FROM material_vendors WHERE material_id = ? AND is_primary = 1 ORDER BY vendor_id LIMIT 1",
        (material_id,),
    ).fetchone()
    return row["vendor_id"] if row else None


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
    q_numbers = {t for t in q_tokens if any(ch.isdigit() for ch in t)}
    contained: dict[str, int] = {}
    for m, aliases in names.items():
        hits = [a for a in aliases if a and set(a.split()) <= q_tokens]
        if not hits:
            continue
        # A generic family alias ("carbon black", "neoprene") must not claim a
        # different grade: "carbon black N330" is not our N550. If every alias that
        # matched is number-free and the query names a grade number this material
        # never uses, it's another grade.
        own_numbers = {t for a in aliases for t in a.split() if any(ch.isdigit() for ch in t)}
        if all(not any(ch.isdigit() for ch in a) for a in hits) and q_numbers - own_numbers:
            continue
        contained[m] = max(len(a.split()) for a in hits)
    if contained:
        top = max(contained.values())
        best = sorted(m for m, size in contained.items() if size == top)
        if len(best) == 1:
            return MatchResult(best[0], "contains", best, 0.95)
        return MatchResult(None, "ambiguous", best, 0.95)

    def numbers(aliases: list[str]) -> set[str]:
        return {t for a in aliases for t in a.split() if any(ch.isdigit() for ch in t)}

    # Same grade rule for near-misses: "carbon black N330" reads 89% like "carbon
    # black N550", but a grade number the material never uses makes it another grade.
    scored = sorted(
        ((max(SequenceMatcher(None, query, a).ratio() for a in aliases), m) for m, aliases in names.items()
         if not (q_numbers - numbers(aliases))),
        reverse=True,
    )
    if not scored or scored[0][0] < FUZZY_ACCEPT:
        return MatchResult(None, "none", [m for _, m in scored[:3]], scored[0][0] if scored else 0.0)

    best_score, best = scored[0]
    close = [m for s, m in scored if best_score - s < FUZZY_MARGIN]
    if len(close) > 1:
        return MatchResult(None, "ambiguous", close, best_score)
    return MatchResult(best, "fuzzy", [best], best_score)
