"""Replay candidates over the 62 cases, K times each.

    python -m evals.promotion.replay --dry-run --batch            # what would run, and the estimated cost
    python -m evals.promotion.replay --batch                      # every candidate at K=8 (baseline at 2K)
    python -m evals.promotion.replay --collect                    # resume waiting on a submitted batch
    python -m evals.promotion.replay --pilot                      # K=3 for every candidate, live calls

Every replay runs the production path (margin_guard.decide.decide) with the
candidate's policy, model and extra rules. Results are cached per candidate in
evals/results/promotion/replays_<id>.json, keyed by case and replay number with a
fingerprint of prompt, model and facts: rerunning is free, raising K runs only the
new replays, and editing a policy reruns only what it touches. Candidates never
share samples, so baseline and candidate replays are independent draws. The
baseline (C0) runs at 2K so it can be split in half for the noise floor (A/A).

--batch sends the same requests through the Message Batches API (50% off, results
in minutes to hours) with the policy prompt cached. The model sees the same
system prompt, facts, schema and effort as a live call; the only difference is
that batches can't carry the refusal fallback, so a refusal is recorded as a
failed call and retried on the next run. Each replay is tagged mode=live|batch.
"""

import argparse
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from anthropic.lib._parse._transform import transform_schema   # what messages.parse uses
from pydantic import TypeAdapter

from evals.eval_scenarios import draft_checks
from margin_guard import llm
from margin_guard.decide import (QuoteDecision, QuoteDecisionWithAbsorb, decide, llm_decide, rule_decision,
                                 system_prompt)

from .candidates import CANDIDATES, Candidate
from .cases import replay_cases

OUT_DIR = Path(__file__).resolve().parent.parent / "results" / "promotion"
EST_COST_PER_CALL = {"claude-sonnet-5-5": 0.0100, "claude-haiku-5-5": 0.0007}   # measured in the pilot
BATCH_DISCOUNT = 0.5
MAX_TOKENS = 8000            # same as margin_guard.llm.parse
DEFAULT_K = 8


def cache_path(cand_id: str) -> Path:
    return OUT_DIR / f"replays_{cand_id}.json"


def pending_batch_path() -> Path:
    return OUT_DIR / "batch_pending.json"


def load_cache(cand_id: str) -> dict:
    p = cache_path(cand_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_cache(cand_id: str, cache: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = {key: v for key, v in cache.items() if "error" not in v}
    cache_path(cand_id).write_text(json.dumps(ok, indent=1), encoding="utf-8")


def fingerprint(cand: Candidate, facts: dict) -> str:
    blob = json.dumps({"system": system_prompt(cand.policy), "model": cand.model, "absorb": cand.allow_absorb,
                       "rules": [r.__name__ for r in cand.extra_rules], "facts": facts}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def k_for(cand_id: str, k: int, pilot: bool = False) -> int:
    return k if pilot or cand_id != "C0" else 2 * k


def _record(case: dict, p: dict, usage: list, mode: str) -> dict:
    rec = {"action": p["action"], "decided_by": p["decided_by"], "rule_id": p["rule_id"],
           "confidence": p["confidence"], "usage": usage, "mode": mode}
    if p["decided_by"] == "error":
        rec["error"] = p["rationale"]
    elif p["decided_by"] == "llm" and p["action"] != "absorb":
        checks = draft_checks(case, p["action"], p["draft_subject"] or "", p["draft_body"] or "")
        rec["draft_ok"], rec["failed_checks"] = all(checks.values()), [k for k, v in checks.items() if not v]
    return rec


def replay_once(cand: Candidate, case: dict) -> dict:
    log: list = []

    def decider(facts):
        return llm_decide(facts, model=cand.model, log=log, policy=cand.policy, allow_absorb=cand.allow_absorb)

    return _record(case, decide(case["facts"], decider, cand.extra_rules), log, "live")


def pending_jobs(cand: Candidate, cases: list[dict], k: int, cache: dict) -> list[tuple[dict, int, str]]:
    jobs = []
    for case in cases:
        fp = fingerprint(cand, case["facts"])
        for r in range(k):
            hit = cache.get(f"{case['id']}:{r}")
            if not (hit and hit.get("fp") == fp and "error" not in hit):
                jobs.append((case, r, fp))
    return jobs


def run_candidate(cand: Candidate, cases: list[dict], k: int, workers: int = 6) -> dict:
    """Live calls, several at a time."""
    cache = load_cache(cand.id)
    jobs = pending_jobs(cand, cases, k, cache)
    if not jobs:
        return cache
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(replay_once, cand, case): (case, r, fp) for case, r, fp in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            case, r, fp = futures[fut]
            with lock:
                cache[f"{case['id']}:{r}"] = {**fut.result(), "fp": fp}
                if i % 25 == 0:
                    save_cache(cand.id, cache)
                    print(f"  {cand.id}: {i}/{len(jobs)}", flush=True)
    save_cache(cand.id, cache)
    return cache


# --- batch mode -------------------------------------------------------------

def _schema(cand: Candidate) -> type[QuoteDecision]:
    return QuoteDecisionWithAbsorb if cand.allow_absorb else QuoteDecision


def batch_params(cand: Candidate, facts: dict) -> dict:
    """The request llm_decide sends, minus the refusal fallback, with the system prompt cached."""
    fmt = {"type": "json_schema", "schema": transform_schema(TypeAdapter(_schema(cand)).json_schema())}
    return {
        "model": cand.model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": system_prompt(cand.policy), "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": json.dumps(facts, indent=2)}],
        "output_config": {"effort": "low", "format": fmt},
    }


def _custom_id(cand_id: str, case_id: str, r: int) -> str:
    return f"{cand_id}__{case_id}__{r}"


def submit_batch(cand_ids: list[str], cases: list[dict], k: int, pilot: bool = False) -> str | None:
    """Settle rule-decided replays locally, send the rest as one batch. Returns the batch id."""
    if pending_batch_path().exists():
        raise SystemExit(f"A batch is already pending ({pending_batch_path().name}); run with --collect first.")
    requests, fps = [], {}
    for cid in cand_ids:
        cand = CANDIDATES[cid]
        cache = load_cache(cid)
        settled = 0
        for case, r, fp in pending_jobs(cand, cases, k_for(cid, k, pilot), cache):
            if rule_decision(case["facts"], cand.extra_rules):
                p = decide(case["facts"], lambda f: None, cand.extra_rules)
                cache[f"{case['id']}:{r}"] = {**_record(case, p, [], "rule"), "fp": fp}
                settled += 1
                continue
            cid_ = _custom_id(cid, case["id"], r)
            requests.append({"custom_id": cid_, "params": batch_params(cand, case["facts"])})
            fps[cid_] = fp
        if settled:
            save_cache(cid, cache)
    if not requests:
        return None
    batch = llm.client().messages.batches.create(requests=requests)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pending_batch_path().write_text(json.dumps({"id": batch.id, "fingerprints": fps}, indent=1), encoding="utf-8")
    print(f"Submitted batch {batch.id}: {len(requests)} requests")
    return batch.id


def _decision_from(msg, schema: type[QuoteDecision]) -> QuoteDecision:
    if msg.stop_reason == "refusal":
        raise llm.LLMRefusal(f"model declined the request: {getattr(msg, 'stop_details', None)}")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise ValueError(f"no structured output (stop_reason={msg.stop_reason})")
    return schema.model_validate_json(text)


def collect_batch(cases: list[dict], poll_seconds: int = 30) -> dict:
    """Wait for the pending batch, then write its results into the candidates' caches."""
    pending = json.loads(pending_batch_path().read_text(encoding="utf-8"))
    client = llm.client()
    while True:
        batch = client.messages.batches.retrieve(pending["id"])
        if batch.processing_status == "ended":
            break
        c = batch.request_counts
        print(f"  {pending['id']}: {batch.processing_status}, {c.processing} processing, "
              f"{c.succeeded} done, {c.errored} errored", flush=True)
        time.sleep(poll_seconds)

    by_id = {c["id"]: c for c in cases}
    caches: dict[str, dict] = {}
    usage, errors = [], []
    for res in client.messages.batches.results(pending["id"]):
        cid, case_id, r = res.custom_id.split("__")
        cand, case = CANDIDATES[cid], by_id[case_id]
        cache = caches.setdefault(cid, load_cache(cid))
        log: list = []
        if res.result.type == "succeeded":
            msg = res.result.message
            u = msg.usage
            log.append({"model": cand.model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
                        "cache_read_input_tokens": u.cache_read_input_tokens or 0, "batch": True})

            def decider(facts, msg=msg, cand=cand):
                return _decision_from(msg, _schema(cand))
        else:
            def decider(facts, res=res):
                raise RuntimeError(f"batch request {res.result.type}: {getattr(res.result, 'error', '')}")
        rec = _record(case, decide(case["facts"], decider, cand.extra_rules), log, "batch")
        cache[f"{case_id}:{r}"] = {**rec, "fp": pending["fingerprints"][res.custom_id]}
        usage += log
        if "error" in rec:
            errors.append(rec["error"])
    for cid, cache in caches.items():
        save_cache(cid, cache)
    pending_batch_path().unlink()
    print(f"  collected: ${replay_cost(usage):.2f} spent"
          + (f", {len(errors)} failed (rerun --batch to retry); first: {errors[0][:300]}" if errors else ""))
    return caches


def replay_cost(entries: list[dict]) -> float:
    """Cost of replay calls: live entries at list price, batch entries at 50% with cache pricing."""
    total = 0.0
    for e in entries:
        p_in, p_out = llm.PRICES.get(e["model"], (0.0, 0.0))
        cost = (e["input_tokens"] * p_in + e.get("cache_creation_input_tokens", 0) * p_in * 1.25
                + e.get("cache_read_input_tokens", 0) * p_in * 0.1 + e["output_tokens"] * p_out) / 1e6
        total += cost * (BATCH_DISCOUNT if e.get("batch") else 1.0)
    return total


def outcomes(cand: Candidate, cases: list[dict], k: int, cache: dict | None = None) -> dict[str, list[str]]:
    """{case_id: [action per replay]} for replays 0..k-1 that exist and match the current fingerprint."""
    cache = load_cache(cand.id) if cache is None else cache
    out = {}
    for case in cases:
        fp = fingerprint(cand, case["facts"])
        acts = [h["action"] for r in range(k)
                if (h := cache.get(f"{case['id']}:{r}")) and h.get("fp") == fp and "error" not in h]
        out[case["id"]] = acts
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", nargs="+", default=list(CANDIDATES), choices=list(CANDIDATES))
    ap.add_argument("--k", type=int, default=DEFAULT_K, help="replays per case (default %(default)s; C0 runs 2K)")
    ap.add_argument("--pilot", action="store_true", help="K=3 for the chosen candidates (C0 too)")
    ap.add_argument("--batch", action="store_true", help="send through the Message Batches API (50%% off)")
    ap.add_argument("--collect", action="store_true", help="wait for the pending batch and save its results")
    ap.add_argument("--dry-run", action="store_true", help="show what would run and the estimated cost")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    k = 3 if args.pilot else args.k

    cases = replay_cases()
    if args.collect:
        if not pending_batch_path().exists():
            raise SystemExit("No pending batch.")
        collect_batch(cases)
        return

    total = 0.0
    for cid in args.candidates:
        cand = CANDIDATES[cid]
        kk = k_for(cid, k, args.pilot)
        jobs = pending_jobs(cand, cases, kk, load_cache(cid))
        # Rule-settled replays cost nothing; count only the ones that reach the model.
        llm_jobs = sum(1 for case, _, _ in jobs if not rule_decision(case["facts"], cand.extra_rules))
        est = llm_jobs * EST_COST_PER_CALL.get(cand.model, 0.01) * (BATCH_DISCOUNT if args.batch else 1.0)
        total += est
        print(f"{cid} {cand.title}: {len(cases)} cases x K={kk} -> {len(jobs)} to run "
              f"({llm_jobs} model calls, ~${est:.2f})")
        if args.dry_run or args.batch or not jobs:
            continue
        before = len(llm.usage_log)
        cache = run_candidate(cand, cases, kk, args.workers)
        failed = [cache.get(f"{case['id']}:{r}", {"error": "missing"}) for case, r, _ in jobs]
        failed = [str(f["error"]) for f in failed if "error" in f]
        print(f"  done: ${replay_cost(llm.usage_log[before:]):.2f} spent"
              + (f", {len(failed)} failed calls (rerun to retry)" if failed else ""))
        if failed:
            print(f"  first error: {failed[0][:300]}")
    note = " before prompt-caching savings" if args.batch else ""
    print(f"Estimated total: ~${total:.2f}{note}" + (" (dry run, nothing called)" if args.dry_run else ""))

    if args.batch and not args.dry_run:
        if submit_batch(args.candidates, cases, k, args.pilot):
            print("Waiting for results (safe to stop with Ctrl+C; resume with --collect)...")
            collect_batch(cases)


if __name__ == "__main__":
    main()
