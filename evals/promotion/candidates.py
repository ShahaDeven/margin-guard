"""Candidate changes the gate decides on, each with its own answer key.

A policy change also changes what "correct" means, so every candidate carries an
answer key written here, independently of margin_guard.decide (the same way
evals/reference_policy.py is). A key maps a case to its answer, starting from the
case's baseline answer (`case["expected"]`, the current policy's). The gate scores baseline and candidate replays
with the candidate's key: "fixed" means the change moved behavior to what the
new policy wants, "regressed" means it broke something that was right.

Targets are the cases the change is meant to fix: every case whose answer the
new key changes, plus any named explicitly (a miss the change should repair).
"""

from dataclasses import dataclass, field
from typing import Callable

from margin_guard.config import MODEL, ROOT
from margin_guard.decide import Rule

POLICIES = ROOT / "data" / "policies"
DE_MINIMIS_USD = 50


def de_minimis_rule(facts: dict) -> tuple[str, str, str] | None:
    """C1a: the de-minimis rule as code. Runs only for below-floor quotes (after the built-in rules)."""
    if facts["exposure_usd"] < DE_MINIMIS_USD:
        return ("absorb", "de_minimis",
                f"Only ${facts['exposure_usd']:,.2f} at risk, under the ${DE_MINIMIS_USD} de-minimis line; "
                "keeping the quoted price.")
    return None


def baseline_key(case: dict) -> str:
    return case["expected"]


def de_minimis_key(case: dict) -> str:
    """Current policy + absorb any below-floor increase under the de-minimis line."""
    base = case["expected"]
    if base in ("honor", "absorb"):       # settled before the below-floor branch
        return base
    return "absorb" if case["facts"]["exposure_usd"] < DE_MINIMIS_USD else base


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    trigger: str                          # what was discovered that led to this change
    policy_file: str = "v1_current.md"
    model: str = MODEL
    allow_absorb: bool = False
    extra_rules: tuple[Rule, ...] = ()
    key: Callable[[dict], str] = baseline_key
    explicit_targets: tuple[str, ...] = ()
    control: bool = False                 # deliberately bad: the gate should reject it
    tags: tuple[str, ...] = field(default=())

    @property
    def policy(self) -> str:
        return (POLICIES / self.policy_file).read_text(encoding="utf-8")

    def targets(self, cases: list[dict]) -> list[str]:
        changed = [c["id"] for c in cases if self.key(c) != c["expected"]]
        return changed + [t for t in self.explicit_targets if t not in changed]


BASELINE = Candidate(
    "C0", "Baseline (nothing changed)",
    "Run against itself to measure the noise floor: what flips when nothing changed.")

CANDIDATES = {c.id: c for c in [
    BASELINE,
    Candidate(
        "C1a", "De-minimis rule as code (absorb < $50 at risk)",
        "Reviewer override on Q-2026-0169: absorbed a ~$30 increase that Claude sent to a call.",
        extra_rules=(de_minimis_rule,), key=de_minimis_key, tags=("policy_change", "code")),
    Candidate(
        "C1b", "De-minimis rule as policy text (absorb < $50 at risk)",
        "Same override as C1a; same intent, written into the prompt instead of code.",
        policy_file="v2_deminimis.md", allow_absorb=True, key=de_minimis_key, tags=("policy_change", "prompt")),
    Candidate(
        "C2", "Clarify notes that set their own call condition",
        "S24 (key account, $8k, 'call over $10k') wrong 3/3 runs at confidence 0.55-0.60.",
        policy_file="v2_clarified.md", explicit_targets=("S24",), tags=("clarification", "prompt")),
    Candidate(
        "C3a", "Tidy-up: soften the contract-note override",
        "Control: reads like a harmless wording cleanup; weakens the rule notes depend on.",
        policy_file="v2_bad_soft.md", control=True, tags=("control", "prompt")),
    Candidate(
        "C3b", "Tidy-up: drop the contract-note override",
        "Control: a shorter policy; removes the override sentence entirely.",
        policy_file="v2_bad_removed.md", control=True, tags=("control", "prompt")),
    Candidate(
        "C4", "Swap Sonnet for Haiku (~15x cheaper)",
        "Cost: distill onto a cheaper model if nothing regresses.",
        model="claude-haiku-5-5", tags=("model_swap",)),
]}
