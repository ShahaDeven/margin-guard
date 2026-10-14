"""Label every case and decide Promote / Hold / Reject for a candidate.

Both sides are scored with the candidate's answer key, case by case:

    fixed        candidate significantly more often right than baseline
    regressed    candidate significantly more often wrong
    flaky        not significant, and at least one side is neither always right nor always wrong
    stable_pass  always right on both sides
    stable_fail  always wrong on both sides

Significance is a two-sided Fisher exact test per case with Benjamini-Hochberg
correction (alpha 0.05), so checking many cases doesn't manufacture regressions. From
version 3 the targets (named before any replay) are their own family and the other
cases another, each corrected separately: a fix the change was built for isn't diluted
by the 55 cases it should leave alone. Versions 1 and 2 correct across all 62 at once.

    Reject   any case regressed
    Hold     a target isn't significantly fixed, or a non-target case dropped by
             >= HOLD_DROP without reaching significance (needs more replays to tell)
    Promote  otherwise

Version 2 of the hold rule uses the noise floor: a drop on a case already known to
be noisy (not always right or always wrong in the baseline sample, or flagged by the
baseline-vs-baseline run) needs significance, not just size, before it holds a
change. Version 1 held on any >= HOLD_DROP drop, and the A/A run showed that is
fooled by noise: C1a was held over S24, a case whose prompt C1a doesn't touch.

`naive_gate` is what comparing single runs does (and what K=1 forces): any drop is a
regression, any rise on a target is a fix. The replays-needed curve compares the two.
"""

from dataclasses import dataclass, field

from .candidates import Candidate
from .stats import benjamini_hochberg, fisher_exact, paired_bootstrap, wilson

ALPHA = 0.05
HOLD_DROP = 0.20


@dataclass
class CaseRow:
    id: str
    target: bool
    expected: str
    base_right: int
    base_n: int
    cand_right: int
    cand_n: int
    p: float = 1.0
    p_adj: float = 1.0
    label: str = ""

    @property
    def base_rate(self) -> float:
        return self.base_right / self.base_n if self.base_n else 0.0

    @property
    def cand_rate(self) -> float:
        return self.cand_right / self.cand_n if self.cand_n else 0.0

    def ci(self, side: str) -> tuple[float, float]:
        return wilson(self.cand_right, self.cand_n) if side == "cand" else wilson(self.base_right, self.base_n)


@dataclass
class GateResult:
    candidate: str
    verdict: str
    reasons: list[str]
    rows: list[CaseRow]
    accuracy_base: float
    accuracy_cand: float
    diff: tuple[float, float, float]           # mean per-case change in accuracy, 95% CI
    counts: dict[str, int] = field(default_factory=dict)


def _rows(cand: Candidate, cases: list[dict], base: dict[str, list[str]],
          cand_actions: dict[str, list[str]]) -> list[CaseRow]:
    targets = set(cand.targets(cases))
    rows = []
    for c in cases:
        want = cand.key(c)
        b, a = base.get(c["id"], []), cand_actions.get(c["id"], [])
        if not b or not a:
            continue
        rows.append(CaseRow(c["id"], c["id"] in targets, want, sum(x == want for x in b), len(b),
                            sum(x == want for x in a), len(a)))
    return rows


def gate(cand: Candidate, cases: list[dict], base: dict[str, list[str]],
         cand_actions: dict[str, list[str]], alpha: float = ALPHA, *,
         known_flaky: frozenset[str] = frozenset(), version: int = 3, bootstrap: bool = True) -> GateResult:
    rows = _rows(cand, cases, base, cand_actions)
    for r in rows:
        r.p = fisher_exact(r.cand_right, r.cand_n - r.cand_right, r.base_right, r.base_n - r.base_right)
    families = ([[r for r in rows if r.target], [r for r in rows if not r.target]] if version >= 3 else [rows])
    for fam in families:
        for r, adj in zip(fam, benjamini_hochberg([r.p for r in fam])):
            r.p_adj = adj
    for r in rows:
        if r.p_adj < alpha:
            r.label = "fixed" if r.cand_rate > r.base_rate else "regressed"
        elif r.base_rate == r.cand_rate == 1.0:
            r.label = "stable_pass"
        elif r.base_rate == r.cand_rate == 0.0:
            r.label = "stable_fail"
        else:
            r.label = "flaky"

    reasons = []
    regressed = [r.id for r in rows if r.label == "regressed"]
    unfixed = [r.id for r in rows if r.target and r.label != "fixed"]
    def noisy(r: CaseRow) -> bool:
        return version >= 2 and (r.id in known_flaky or 0.0 < r.base_rate < 1.0)

    unresolved = [r.id for r in rows if not r.target and r.label == "flaky"
                  and r.base_rate - r.cand_rate >= HOLD_DROP and not noisy(r)]
    if regressed:
        verdict = "reject"
        reasons.append(f"regressed: {', '.join(regressed)}")
    elif unfixed or unresolved:
        verdict = "hold"
        if unfixed:
            reasons.append(f"target not reliably fixed: {', '.join(unfixed)}")
        if unresolved:
            reasons.append(f"dropped >= {HOLD_DROP:.0%} but not significant (needs more replays): {', '.join(unresolved)}")
    else:
        verdict = "promote"
    return _result(cand, rows, verdict, reasons, bootstrap)


def naive_gate(cand: Candidate, cases: list[dict], base: dict[str, list[str]],
               cand_actions: dict[str, list[str]], bootstrap: bool = True) -> GateResult:
    rows = _rows(cand, cases, base, cand_actions)
    for r in rows:
        r.label = ("fixed" if r.cand_rate > r.base_rate else "regressed" if r.cand_rate < r.base_rate
                   else "stable_pass" if r.cand_rate == 1.0 else "stable_fail" if r.cand_rate == 0.0 else "flaky")
    regressed = [r.id for r in rows if r.label == "regressed"]
    unfixed = [r.id for r in rows if r.target and r.label != "fixed"]
    verdict = "reject" if regressed else "hold" if unfixed else "promote"
    reasons = ([f"regressed: {', '.join(regressed)}"] if regressed else []) + \
              ([f"target not fixed: {', '.join(unfixed)}"] if unfixed else [])
    return _result(cand, rows, verdict, reasons, bootstrap)


def _result(cand: Candidate, rows: list[CaseRow], verdict: str, reasons: list[str],
            bootstrap: bool = True) -> GateResult:
    n = len(rows) or 1
    diffs = [r.cand_rate - r.base_rate for r in rows]
    counts = {lab: sum(r.label == lab for r in rows)
              for lab in ("fixed", "regressed", "flaky", "stable_pass", "stable_fail")}
    return GateResult(cand.id, verdict, reasons, rows,
                      accuracy_base=sum(r.base_rate for r in rows) / n,
                      accuracy_cand=sum(r.cand_rate for r in rows) / n,
                      diff=(paired_bootstrap(diffs) if bootstrap   # the curve skips the interval: thousands of calls
                            else (sum(diffs) / n, float("nan"), float("nan"))),
                      counts=counts)
