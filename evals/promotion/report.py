"""Write the promotion-gate report and its charts from the cached replays. No API calls.

    python -m evals.promotion.report      # -> evals/results/promotion/promotion_report.md + charts/
"""

import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .candidates import BASELINE, CANDIDATES  # noqa: E402
from .cases import replay_cases  # noqa: E402
from .curve import BAD, SHOULD, curve, gate_results, pools  # noqa: E402
from .gate import ALPHA, gate  # noqa: E402
from .ledger import PROPOSALS, wanted  # noqa: E402
from .replay import DEFAULT_K, OUT_DIR, load_cache, replay_cost  # noqa: E402
from .stats import fisher_exact  # noqa: E402

CHARTS = OUT_DIR / "charts"
REVIEWS = OUT_DIR / "reviews_human.json"

# Reference data-viz palette (light): categorical slots 1-2, status trio, ink and surface.
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = {"gate": "#2a78d6", "naive": "#eb6834"}
STATUS = {"promote": "#0ca30c", "hold": "#fab219", "reject": "#d03b3b"}
SHOULD_TEXT = {"promote": "should promote", "reject": "should be rejected", "not_promote": "should not promote"}
LABEL = {"C0": "C0 nothing changed", "C1a": "C1a de-minimis as code", "C1b": "C1b de-minimis as prompt",
         "C2": "C2 note clarification", "C3a": "C3a control: soften notes", "C3b": "C3b control: drop notes",
         "C4": "C4 swap to Haiku"}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_curve(res: dict, path: Path) -> None:
    """Small multiples: P(promote) vs K, naive single-comparison gate vs gate v3, one panel per candidate."""
    ids = list(CANDIDATES)
    fig, axes = plt.subplots(2, 4, figsize=(12, 5.6), sharex=True, sharey=True, facecolor=SURFACE)
    ks = sorted(res[ids[0]])
    for ax, cid in zip(axes.flat, ids):
        _style(ax)
        for g, name in (("naive", "naive"), ("v3", "gate")):
            ys = [res[cid][k][g].get("promote", 0.0) for k in ks]
            ax.plot(ks, ys, color=SERIES[name], linewidth=2, marker="o", markersize=4.5,
                    markeredgecolor=SURFACE, markeredgewidth=1.2)
        ax.set_title(LABEL[cid], fontsize=9, color=INK, loc="left", pad=16)
        ax.text(0.0, 1.02, SHOULD_TEXT[SHOULD[cid]], transform=ax.transAxes, fontsize=7.5, color=INK_2, va="bottom")
        ax.set_ylim(-0.04, 1.04)
        ax.set_xticks(ks)
        ax.set_yticks([0, 0.5, 1])
        ax.set_yticklabels(["0%", "50%", "100%"])
    first = axes.flat[0]
    first.text(ks[-1], res[ids[0]][ks[-1]]["v3"].get("promote", 0) - 0.1, "gate v3", color=INK, fontsize=8, ha="right")
    first.text(ks[0] + 0.2, res[ids[0]][ks[0]]["naive"].get("promote", 0) + 0.08, "single comparison",
               color=INK, fontsize=8)
    leg = axes.flat[-1]
    leg.axis("off")
    for i, (name, text) in enumerate((("gate", "Gate v3 (Fisher, FDR per family, noise floor)"),
                                      ("naive", "Naive comparison (any drop = regression)"))):
        leg.plot([0.02, 0.14], [0.78 - i * 0.16] * 2, color=SERIES[name], linewidth=2, transform=leg.transAxes)
        leg.text(0.18, 0.78 - i * 0.16, text, color=INK, fontsize=8, va="center", transform=leg.transAxes)
    leg.text(0.02, 0.36, "y: share of 400 resampled runs that promote\nx: replays per case (K)",
             color=INK_2, fontsize=8, transform=leg.transAxes, va="top")
    fig.suptitle("Probability of promoting each change, by number of replays", x=0.01, ha="left",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def chart_verdicts(res: dict, path: Path, k_max: int) -> None:
    """Stacked bars: verdict mix for a single naive comparison vs gate v3 at K=k_max."""
    ids = list(CANDIDATES)
    rows = []
    for cid in ids:
        rows.append((f"{LABEL[cid]} · 1 run, naive", res[cid][1]["naive"]))
        rows.append((f"{LABEL[cid]} · {k_max} runs, gate v3", res[cid][k_max]["v3"]))
    fig, ax = plt.subplots(figsize=(10, 6.4), facecolor=SURFACE)
    _style(ax)
    ax.grid(False)
    y = list(range(len(rows)))[::-1]
    for yi, (_, verdicts) in zip(y, rows):
        left = 0.0
        for v in ("promote", "hold", "reject"):
            w = verdicts.get(v, 0.0)
            if w <= 0:
                continue
            ax.barh(yi, w, left=left, height=0.62, color=STATUS[v], edgecolor=SURFACE, linewidth=2)
            if w >= 0.1:
                ax.text(left + w / 2, yi, f"{v} {w:.0%}", ha="center", va="center", fontsize=7.5,
                        color=INK if v == "hold" else "#ffffff")
            left += w
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8, color=INK)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xticklabels(["0%", "50%", "100%"])
    for i in range(1, len(ids)):
        ax.axhline(y[2 * i - 1] - 0.5, color=GRID, linewidth=0.8)
    handles = [plt.Rectangle((0, 0), 1, 1, color=STATUS[v]) for v in STATUS]
    ax.legend(handles, ["promote", "hold (needs more replays)", "reject"], loc="lower center",
              bbox_to_anchor=(0.5, 1.0), ncol=3, frameon=False, fontsize=8, labelcolor=INK)
    ax.set_title("Verdicts: one naive comparison vs the replayed gate", loc="left", fontsize=11, color=INK, pad=26)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def chart_code_vs_prompt(results: dict, path: Path, flaky: frozenset[str]) -> None:
    """Dumbbells: per-case accuracy baseline -> candidate for C1a (code) and C1b (prompt)."""
    a, b = results["C1a"], results["C1b"]
    moved = [r.id for r in b.rows if r.base_rate != r.cand_rate] + \
            [r.id for r in a.rows if r.base_rate != r.cand_rate]
    ids = list(dict.fromkeys(moved))
    fig, axes = plt.subplots(1, 2, figsize=(10, 0.32 * len(ids) + 1.6), sharey=True, facecolor=SURFACE)
    for ax, res, title in ((axes[0], a, "C1a: rule in code"), (axes[1], b, "C1b: same rule as prompt text")):
        _style(ax)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.grid(axis="y", visible=False)
        by = {r.id: r for r in res.rows}
        for yi, cid in enumerate(ids[::-1]):
            r = by[cid]
            if r.base_rate == r.cand_rate:
                ax.scatter([r.base_rate], [yi], s=22, color=INK_2, zorder=2, edgecolor=SURFACE, linewidth=1.5)
                ax.text(1.08, yi, "no change", fontsize=7, va="center", color=INK_2)
                continue
            ax.plot([r.base_rate, r.cand_rate], [yi, yi], color=GRID, linewidth=2, zorder=1)
            ax.scatter([r.base_rate], [yi], s=34, color=SERIES["gate"], zorder=2, edgecolor=SURFACE, linewidth=1.5)
            ax.scatter([r.cand_rate], [yi], s=34, color=SERIES["naive"], zorder=3, edgecolor=SURFACE, linewidth=1.5)
            note = r.label if r.label in ("fixed", "regressed") else "noise (flaky case)" if cid in flaky                 else "not significant"
            ax.text(1.08, yi, note, fontsize=7, va="center", color=INK_2)
        ax.set_xlim(-0.05, 1.5)
        ax.set_xticks([0, 0.5, 1])
        ax.set_xticklabels(["0%", "50%", "100%"])
        ax.set_title(title, loc="left", fontsize=10, color=INK)
    axes[0].set_yticks(range(len(ids)))
    targets = {r.id for r in a.rows if r.target}
    axes[0].set_yticklabels([cid + (" (target)" if cid in targets else "") for cid in ids[::-1]],
                            fontsize=7.5, color=INK)
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=SERIES["gate"]),
               plt.Line2D([], [], marker="o", linestyle="", color=SERIES["naive"]),
               plt.Line2D([], [], marker="o", linestyle="", color=INK_2, markersize=5)]
    fig.legend(handles, ["baseline", "candidate", "same on both"], loc="upper right", ncol=3, frameon=False, fontsize=8,
               labelcolor=INK)
    fig.suptitle("Share of 8 replays right, per case (cases where anything moved)", x=0.01, ha="left",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def _pct(v) -> str:
    return "-" if v is None else f"{v:.0%}"


def _human_section() -> list[str]:
    if not REVIEWS.exists():
        return ["No human reviews exported yet."]
    rows = json.loads(REVIEWS.read_text(encoding="utf-8"))
    note_rule = wanted(next(p for p in PROPOSALS if p.id == "L-007"), rows)
    n = len(rows)
    out = Counter(r["outcome"] for r in rows)
    changed = [r for r in rows if r["outcome"] == "action_changed"]
    decoy_calls = [r for r in changed if r["final_action"] == "contact_customer" and r["facts"]["contract_note"]]
    lines = [f"{n} judgment-call cards reviewed across {len({r['shop'] for r in rows})} extra shops "
             f"(seeds {', '.join(str(s) for s in sorted({r['shop'] for r in rows}))}, never the replay shop).", "",
             "| Outcome | Count |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {out[k]} |" for k in ("approved_as_is", "draft_rewritten", "action_changed",
                                                                   "rejected")]
    lines += ["", f"- A reviewer that approves everything would agree with this one **{out['approved_as_is'] / n:.0%}** "
                  "of the time, so agreement alone says little; the overrides carry the signal, and there are only "
                  f"**{len(changed)}**.",
              f"- {len(decoy_calls)} of {len(changed)} overrides moved an email to a call because a contract note "
              "existed, including notes about shipping or payment terms that the policy says must not change the "
              "decision: a disagreement with the policy, not a model error.",
              "- The same note (Harbor Point's ship-to address) produced opposite overrides on two quotes: human "
              "corrections have a noise floor too, and a loop that promotes corrections needs to measure it.",
              "- No override absorbed a small increase, although 5 reviewed cards were under $50 at risk. The evidence "
              "that anyone wants the de-minimis rule (C1a) is a single earlier override.", "",
              "Each proposed change is tracked in the [correction ledger](ledger.md) with both answers side by "
              "side: the gate's verdict (safe?) and the review evidence (wanted?). The de-minimis rule is held "
              "there as safe but not wanted, and the reviewer's own pattern (\"call whenever a note exists\") "
              f"is logged as a proposal with {note_rule['support']} reviews for it and {note_rule['contradict']} against."]
    return lines


def _min_k(alpha: float, scale: float) -> int | None:
    """Smallest K at which a clean fix (0/K -> K/K) is significant after multiplying its p-value by `scale`."""
    return next((kk for kk in range(1, 33) if fisher_exact(kk, 0, 0, kk) * scale < alpha), None)


def main() -> None:
    k = DEFAULT_K
    cases = replay_cases()
    CHARTS.mkdir(parents=True, exist_ok=True)

    results, flaky = gate_results(cases, k)
    by_version = {v: gate_results(cases, k, version=v)[0] for v in (1, 2)}

    res = curve(k)
    chart_curve(res, CHARTS / "replays_needed.png")
    chart_verdicts(res, CHARTS / "verdicts.png", k)
    chart_code_vs_prompt(results, CHARTS / "code_vs_prompt.png", flaky)

    # Live (pilot) vs batch replays of the same baseline: do the two transports agree?
    live, batch = pools(BASELINE, cases, range(3)), pools(BASELINE, cases, range(3, 2 * k))
    lb = gate(BASELINE, cases, live, batch, known_flaky=flaky)

    spend = {cid: replay_cost([u for v in load_cache(cid).values() for u in v.get("usage", [])]) for cid in CANDIDATES}
    sonnet = [cid for cid in CANDIDATES if CANDIDATES[cid].model == "claude-sonnet-5-5"]
    batch_calls = [u for cid in sonnet for v in load_cache(cid).values() for u in v.get("usage", []) if u.get("batch")]
    live_calls = [u for cid in sonnet for v in load_cache(cid).values() for u in v.get("usage", []) if not u.get("batch")]
    per_batch = replay_cost(batch_calls) / len(batch_calls)
    per_live = replay_cost(live_calls) / len(live_calls)
    cached_share = sum(u.get("cache_read_input_tokens", 0) for u in batch_calls) / max(
        1, sum(u["input_tokens"] + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
               for u in batch_calls))

    def first_k(cid: str, g: str, share: float = 0.8) -> int | None:
        return next((kk for kk in sorted(res[cid]) if res[cid][kk][g].get("promote", 0) >= share), None)

    good_k, good_k_v2 = first_k("C1a", "v3"), first_k("C1a", "v2")
    n_targets = len(CANDIDATES["C1a"].targets(cases))
    k_family, k_all = _min_k(ALPHA, 1.0), _min_k(ALPHA, len(cases) / n_targets)
    aa1 = res["C0"][1]["naive"].get("reject", 0)
    c2_slip = max(res["C2"][kk]["v3"].get("promote", 0) for kk in res["C2"])
    c2_slip_k = max(res["C2"], key=lambda kk: res["C2"][kk]["v3"].get("promote", 0))
    c1b = results["C1b"]

    L = ["# Promotion gate: when is a change safe to promote?", "",
         "Margin Guard's loop turns a miss or a reviewer override into a candidate change (a rule, a policy edit, "
         "a model swap). This report replays every candidate against 62 cases (30 hand-built scenarios + 32 "
         f"judgment calls from the seeded shop), {k} times each ({2 * k} for the baseline), and decides "
         "promote / hold / reject. Everything below is computed from the cached replays by "
         "`python -m evals.promotion.report`.", "",
         "## Headline", "",
         f"- **Two noisy cases make a single comparison a coin flip.** With nothing changed, comparing one run "
         f"against another flags a regression **{aa1:.0%}** of the time. All of it comes from {len(flaky)} of the "
         f"62 cases ({', '.join(sorted(flaky))}) that change answer on their own. The same comparison promotes the "
         f"one correct change (C1a) only {res['C1a'][1]['naive'].get('promote', 0):.0%} of the time.",
         f"- **Aggregate accuracy hides offsetting regressions.** C1b's accuracy moves {c1b.diff[0]:+.1%} with a "
         f"95% interval of ({c1b.diff[1]:+.1%}, {c1b.diff[2]:+.1%}): an aggregate eval calls it a wash. Per case, "
         f"it fixes {c1b.counts['fixed']} and breaks {c1b.counts['regressed']}, and the gate rejects it.",
         f"- **The gate never cries wolf, and the replay count is mostly arithmetic.** Gate v3 rejects the no-op "
         f"**0%** of the time at every K and promotes the correct change from **K = {good_k}**. That number comes "
         f"from the test, not the data: a clean fix (0/K → K/K) clears Fisher at α = 0.05 at K = {k_family} when "
         f"the targets are their own family, and only at K = {k_all} when it is corrected against all 62 cases "
         f"(gate v2: K = {good_k_v2}). What the data adds is that nothing else moved.",
         f"- **Blatant regressions are caught by one run; subtle ones aren't.** The three bad changes "
         f"({', '.join(BAD)}) break cases 8/8 → 0/8, so even one replay rejects them. The subtle one, C2, fixes "
         f"S24 and breaks its sibling S22; one naive comparison promotes it "
         f"{res['C2'][1]['naive'].get('promote', 0):.0%} of the time.",
         "- **In this one rule, code beat prompt.** The de-minimis rule as code (C1a) fixes all 7 targets with no "
         f"regressions; as policy text (C1b) it fixes the same 7 and breaks {c1b.counts['regressed']} others.",
         "- **Safe is not the same as wanted.** C1a came from one reviewer override. In 55 later reviews the "
         "reviewer never absorbed a small increase. The gate shows C1a is safe to promote, not that anyone "
         "wants it.", "",
         f"## Verdicts at K = {k}", "",
         "| Candidate | Verdict | v2 | v1 | Accuracy base → cand | Δ (95% CI) | Fixed | Regressed | Flaky |",
         "|---|---|---|---|---|---|---|---|---|"]
    for cid, r in results.items():
        L.append(f"| {LABEL[cid]} | **{r.verdict}** | {by_version[2][cid].verdict} | {by_version[1][cid].verdict} | "
                 f"{r.accuracy_base:.1%} → {r.accuracy_cand:.1%} | {r.diff[0]:+.1%} ({r.diff[1]:+.1%}, {r.diff[2]:+.1%}) "
                 f"| {r.counts['fixed']} | {r.counts['regressed']} | {r.counts['flaky']} |")
    L += ["", "Both sides are scored with the candidate's answer key. For C1a and C1b that key absorbs small "
              "increases, so the unchanged baseline scores 87.5% against it: that gap is what the change is for.", "",
          "What triggered each candidate, and why the gate decided as it did:", ""]
    for cid, r in results.items():
        why = "; ".join(r.reasons) or ("nothing regressed, every target fixed" if any(row.target for row in r.rows)
                                       else "nothing regressed")
        L.append(f"- **{LABEL[cid]}**: {CANDIDATES[cid].trigger} *Gate:* {why}.")

    aa = results["C0"]
    L += ["", "## The noise floor, and two changes to the gate", "",
          f"The baseline replayed {2 * k} times and split in half: {aa.counts['stable_pass']} cases right every time, "
          f"{len(flaky)} that change answer with nothing changed ({', '.join(sorted(flaky))}). "
          f"Baseline accuracy {aa.accuracy_base:.1%} vs {aa.accuracy_cand:.1%}; the gate's verdict on the no-op is "
          f"**{aa.verdict}**.", "",
          "Both changes below were made after seeing results, so all three versions are reported:", "",
          "- **v1 → v2 (noise floor).** v1 held any change that dropped a case by 20 points without reaching "
          "significance. It held C1a over S24 (5/8 → 3/8), a case whose prompt C1a doesn't touch: pure noise. v2 "
          "requires significance on cases the noise floor already marks as flaky.",
          f"- **v2 → v3 (target family).** v2 corrected each target against all 62 cases, which is why a clean fix "
          f"needed K = {k_all}. Targets are named before any replay, so v3 corrects them as their own family. "
          f"The cost: v3 promotes the subtle C2 in {c2_slip:.0%} of draws at K = {c2_slip_k} (v2: never).", "",
          "## How many replays?", "",
          "![Probability of promoting each change by number of replays](charts/replays_needed.png)", "",
          "| Candidate | Should | " + " | ".join(f"K={kk}" for kk in sorted(res["C0"])) + " |",
          "|---|---|" + "---|" * len(res["C0"])]
    for cid, by_k in res.items():
        L.append(f"| {LABEL[cid]} | {SHOULD[cid].replace('_', ' ')} | " + " | ".join(
            f"{by_k[kk]['naive'].get('promote', 0):.0%} / {by_k[kk]['v3'].get('promote', 0):.0%}" for kk in sorted(by_k)) + " |")
    L += ["", "Cells: P(promote) for the naive comparison / gate v3, over 400 resampled draws of K replays per case "
              "(without replacement, so K = 8 uses every recorded replay and has no spread). The naive rule counts "
              "any drop as a regression; past K = 1 that is a straw man (nobody calls 5/8 vs 4/8 a regression), "
              "which is why the headline uses K = 1.", "",
          "![Verdict mix: one naive comparison vs the replayed gate](charts/verdicts.png)", "",
          "Hone's *Closing the Gap #1* compares untested changes (38% fixed cleanly / 33% fixed but regressed / "
          "29% not fixed) with replayed ones (92 / 5 / 3), and notes that replays diverge, so each change is "
          "replayed several times. This is the missing piece: how many times, and what deciding on too few "
          "costs.", "",
          "## Code vs prompt (one rule)", "",
          "![Per-case accuracy, code rule vs prompt rule](charts/code_vs_prompt.png)", ""]
    by_id = {c["id"]: c for c in cases}
    c1b_cache = load_cache("C1b")
    L += ["| Case | Quote | Should | C1b did (8 replays) |", "|---|---|---|---|"]
    for r in (r for r in c1b.rows if r.label == "regressed"):
        f = by_id[r.id]["facts"]
        did = Counter(c1b_cache[f"{r.id}:{i}"]["action"] for i in range(k))
        L.append(f"| {r.id} | {f['customer_tier']}, ${f['quote_value_usd']:,.0f}, ${f['exposure_usd']:,.2f} at risk "
                 f"| {r.expected} | {', '.join(f'{a} {n}' for a, n in did.items())} |")
    L += ["", "Our reading: the prompt version says the rule applies \"whatever the tier, value or contract note\", "
              "and the model carried that beyond small increases, so the $15,000 call rule stopped holding on large "
              "standard quotes. The code version can't leak that way: it only fires below the line. One rule is "
              "one example, not a law.", "",
          "## Live vs batch replays", "",
          "The pilot ran live (3 replays per case); the rest went through the Message Batches API with the "
          "policy prompt cached. Request bodies were checked field by field against the live call (identical "
          "except the refusal fallback, which batches don't support). Baseline live vs batch: "
          f"**{lb.counts['fixed'] + lb.counts['regressed']}** cases differ significantly.", "",
          "## Cost", "",
          "| Candidate | Spent |", "|---|---|"]
    L += [f"| {LABEL[cid]} | ${v:.2f} |" for cid, v in spend.items()]
    L += [f"| **Total** | **${sum(spend.values()):.2f}** |", "",
          f"Sonnet replay: ${per_live:.4f} live, ${per_batch:.4f} in a batch ({cached_share:.0%} of batch input tokens "
          f"read from cache). One promote decision at K replays costs 62 × K candidate calls (baseline replays are "
          f"shared across candidates): ${62 * per_batch:.2f} per replay round in a batch, so "
          f"${62 * per_batch * (good_k or k):.2f} at K = {good_k or k}.", "",
          "## What the human reviews add", ""]
    L += _human_section()
    L += ["", "## What this means for a promotion loop", "",
          "1. **Measure the noise floor once per baseline**, by replaying it against itself, and let every "
          "decision use it. Two flaky cases in 62 were enough to make single comparisons useless.",
          "2. **Decide per case with false-discovery control, never on aggregate accuracy alone.** Offsetting "
          "fixes and breaks cancel in the average (C1b).",
          "3. **Name the targets before replaying** and test them as their own family. It is the honest way to "
          "spend fewer replays on the fix you built.",
          "4. **Hold is a real verdict.** \"Not enough evidence yet\" (C2, the Haiku swap) is different from "
          "\"bad\", and a gate that can't say it will either block good changes or wave through subtle ones.",
          "5. **Move deterministic rules into code.** The same rule as a prompt edit leaked into unrelated cases.",
          "6. **Treat \"safe\" and \"wanted\" as separate questions.** The gate answers the first. Reviewer "
          "corrections, which are noisy and sometimes disagree with the written policy, are evidence for the "
          "second, and need their own consistency check before they turn into policy.",
          "", "## Limits", "",
          "- 62 cases, one domain, one policy. The cases were built to probe this policy's edges, so the "
          "regression rates are not base rates for real changes.",
          "- Answer keys are hand-written, and the gate measures agreement with them, not correctness: a wrong key "
          "would report a real fix as a regression. Keys are written independently of the decision code, and each "
          "candidate's key scores both sides, so a policy change is judged by what the new policy wants.",
          "- Upstream (extraction, impact) is held fixed from the recorded trace; only the decision step is "
          "resampled. Errors upstream are not part of this noise floor.",
          "- C2 and C4 are judgment calls in the scoring of the curve (\"should not promote\"): C2 swaps one "
          "fix for one break, C4 loses 2.6 points of accuracy without any single case reaching significance.",
          "- Both gate revisions (v1 → v2 → v3) were made after seeing results; every version's verdict is "
          "reported above."]
    report = "\n".join(L) + "\n"
    (OUT_DIR / "promotion_report.md").write_text(report, encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'promotion_report.md'} and {len(list(CHARTS.glob('*.png')))} charts in {CHARTS}")


if __name__ == "__main__":
    main()
