"""How many replays before a promote decision can be trusted?

For each candidate and each K' = 1..K, draw K' replays per case (without
replacement) from the recorded pools, run the gates, and count verdicts over many
draws. Baseline draws come from all 2K baseline replays; the baseline-vs-baseline
row (C0) draws its two sides from the two disjoint halves. Cases the full A/A run
showed to be noisy are passed to the gate as known flaky: the noise floor is
measured once and used by every decision. (Gate v1 ignores them; v2 and v3 use them.)

    python -m evals.promotion.curve        # prints the table; report.py draws it
"""

import random
from collections import Counter

from .candidates import BASELINE, CANDIDATES, Candidate
from .cases import replay_cases
from .gate import gate, naive_gate
from .replay import DEFAULT_K, fingerprint, load_cache

# What a trustworthy gate should do with each candidate, judged from the full data
# and the design: C1b, C3a and C3b regress significantly at full K; C1a fixes its
# targets and touches nothing else. C2 trades S24 for its sibling S22 and C4 loses
# accuracy on six cases, so promoting either would be wrong; holding or rejecting is fine.
SHOULD = {"C0": "promote", "C1a": "promote", "C1b": "reject", "C2": "not_promote",
          "C3a": "reject", "C3b": "reject", "C4": "not_promote"}
BAD = ("C1b", "C3a", "C3b")


def pools(cand: Candidate, cases: list[dict], replays: range) -> dict[str, list[str]]:
    cache = load_cache(cand.id)
    out = {}
    for c in cases:
        fp = fingerprint(cand, c["facts"])
        out[c["id"]] = [h["action"] for r in replays
                        if (h := cache.get(f"{c['id']}:{r}")) and h.get("fp") == fp and "error" not in h]
    return out


def known_flaky(base_pool: dict[str, list[str]]) -> frozenset[str]:
    """Cases whose baseline replays don't all give the same action."""
    return frozenset(cid for cid, acts in base_pool.items() if len(set(acts)) > 1)


def gate_results(cases: list[dict], k: int = DEFAULT_K, version: int = 3) -> tuple[dict, frozenset[str]]:
    """Each candidate's verdict on all its replays vs the first half of the baseline, plus the noise floor.

    C0 compares the baseline's two halves (the A/A run)."""
    base_all = pools(BASELINE, cases, range(2 * k))
    half_a, half_b = pools(BASELINE, cases, range(k)), pools(BASELINE, cases, range(k, 2 * k))
    flaky = known_flaky(base_all)
    results = {}
    for cid, cand in CANDIDATES.items():
        cand_pool = half_b if cid == "C0" else pools(cand, cases, range(k))
        results[cid] = gate(cand, cases, half_a, cand_pool, known_flaky=flaky, version=version)
    return results, flaky


def _draw(pool: dict[str, list[str]], k: int, rng: random.Random) -> dict[str, list[str]]:
    return {cid: rng.sample(acts, min(k, len(acts))) for cid, acts in pool.items()}


def curve(k_max: int = DEFAULT_K, n_draws: int = 400, seed: int = 7) -> dict:
    """{cand_id: {k: {"naive" | "v1" | "v2" | "v3": {verdict: share of draws}}}}."""
    cases = replay_cases()
    base_all = pools(BASELINE, cases, range(2 * k_max))
    half_a, half_b = pools(BASELINE, cases, range(k_max)), pools(BASELINE, cases, range(k_max, 2 * k_max))
    flaky = known_flaky(base_all)
    rng = random.Random(seed)
    out = {}
    for cid, cand in CANDIDATES.items():
        cand_pool = half_b if cid == "C0" else pools(cand, cases, range(k_max))
        base_pool = half_a if cid == "C0" else base_all
        out[cid] = {}
        for k in range(1, k_max + 1):
            tally = {"naive": Counter(), "v1": Counter(), "v2": Counter(), "v3": Counter()}
            for _ in range(n_draws):
                b, a = _draw(base_pool, k, rng), _draw(cand_pool, k, rng)
                tally["naive"][naive_gate(cand, cases, b, a, bootstrap=False).verdict] += 1
                for v in (1, 2, 3):
                    tally[f"v{v}"][gate(cand, cases, b, a, known_flaky=flaky, version=v,
                                        bootstrap=False).verdict] += 1
            out[cid][k] = {g: {v: n / n_draws for v, n in t.items()} for g, t in tally.items()}
    return out


def main() -> None:
    res = curve()
    ks = sorted(next(iter(res.values())))
    print("P(promote) by K   (naive / gate v3)")
    print("cand  should       " + " ".join(f"K={k:<9}" for k in ks))
    for cid, by_k in res.items():
        cells = [f"{by_k[k]['naive'].get('promote', 0):.2f}/{by_k[k]['v3'].get('promote', 0):.2f}" for k in ks]
        print(f"{cid:<5} {SHOULD[cid]:<12} " + " ".join(f"{c:<11}" for c in cells))
    print("\nP(reject) for C0 (nothing changed: a false alarm)   naive / v3")
    print("  " + "  ".join(f"K={k}: {res['C0'][k]['naive'].get('reject', 0):.2f}/{res['C0'][k]['v3'].get('reject', 0):.2f}"
                           for k in ks))


if __name__ == "__main__":
    main()
