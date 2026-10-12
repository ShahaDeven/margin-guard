"""Thin wrapper around the Claude API for schema-validated outputs."""

import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import MODEL, USE_FALLBACKS

T = TypeVar("T", bound=BaseModel)

# $ per million tokens (input, output), for cost reporting in the evals.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}

# One entry per call: model, tokens, seconds. The evals read it to report cost and latency.
usage_log: list[dict] = []

_client: anthropic.Anthropic | None = None


class LLMRefusal(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _fallback_args(model: str) -> dict:
    """Server-side refusal fallback: a declined request is re-run on Anthropic's
    recommended fallback model instead of failing the run. Haiku has no
    server-side fallback, so it's only sent for models that support it."""
    if not USE_FALLBACKS or model.startswith("claude-haiku"):
        return {}
    return {"extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"},
            "extra_body": {"fallbacks": "default"}}


def parse(system: str, user: str, schema: type[T], *, effort: str = "low", max_tokens: int = 8000,
          model: str | None = None, log: list | None = None) -> T:
    """One Claude call whose response is validated against `schema`.

    Usage goes to the module-wide `usage_log`, and also to `log` when given, so a
    caller running calls concurrently can attribute cost per call."""
    model = model or MODEL
    started = time.perf_counter()
    response = client().messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": effort},
        **_fallback_args(model),
    )
    entry = {
        "model": model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "seconds": round(time.perf_counter() - started, 2),
    }
    usage_log.append(entry)
    if log is not None:
        log.append(entry)
    if response.stop_reason == "refusal":
        raise LLMRefusal(f"model declined the request: {getattr(response, 'stop_details', None)}")
    if response.parsed_output is None:
        raise ValueError(f"no structured output (stop_reason={response.stop_reason})")
    return response.parsed_output


def cost_usd(entries: list[dict]) -> float:
    total = 0.0
    for e in entries:
        p_in, p_out = PRICES.get(e["model"], (0.0, 0.0))
        total += e["input_tokens"] / 1e6 * p_in + e["output_tokens"] / 1e6 * p_out
    return total
