"""Thin wrapper around the Claude API for schema-validated outputs."""

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import MODEL, USE_FALLBACKS

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class LLMRefusal(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def parse(system: str, user: str, schema: type[T], *, effort: str = "low", max_tokens: int = 8000) -> T:
    """One Claude call whose response is validated against `schema`."""
    extra: dict = {}
    if USE_FALLBACKS:
        # Server-side refusal fallback: a declined request is re-run on
        # Anthropic's recommended fallback model instead of failing the run.
        extra["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
        extra["extra_body"] = {"fallbacks": "default"}

    response = client().messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": effort},
        **extra,
    )
    if response.stop_reason == "refusal":
        raise LLMRefusal(f"model declined the request: {getattr(response, 'stop_details', None)}")
    if response.parsed_output is None:
        raise ValueError(f"no structured output (stop_reason={response.stop_reason})")
    return response.parsed_output
