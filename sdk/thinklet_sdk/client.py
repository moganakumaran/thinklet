"""Thinklet SDK — explicit wrapper around Gemini calls.

Usage:
    from thinklet_sdk import ThinkletClient

    tk = ThinkletClient()  # reads env vars
    response = tk.call(
        prompt="What is the capital of France?",
        model="gemini-3.5-flash",
        thinking_level="high",
        task_label="geography_lookup",
    )

The wrapper:
  1. Hashes (model, prompt) into a stable prompt_hash.
  2. Times the call.
  3. Calls Gemini if THINKLET_DEMO_MODE != true AND GEMINI_API_KEY is set;
     otherwise produces a deterministic fake response seeded by prompt_hash.
  4. Extracts usage_metadata (input/output/thinking tokens) when available.
  5. POSTs a span to Thinklet backend.

Demo mode is intentional — the SDK should NEVER fail your real app just
because Thinklet's backend is down. All errors during ingest are swallowed
(and logged once via warnings).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
import warnings
from dataclasses import dataclass
from typing import Any, Optional

import httpx

# Auto-load .env if present (walks up from CWD). Idempotent and safe in apps
# that already loaded it themselves — override=False preserves existing env.
try:
    from dotenv import find_dotenv, load_dotenv
    _envfile = find_dotenv(usecwd=True)
    if _envfile:
        load_dotenv(_envfile, override=False)
except ImportError:
    pass

from .contents import (
    hash_contents,
    normalize_contents,
    redact_contents,
    serialize_contents,
)

THINKING_LEVELS = ("minimal", "low", "medium", "high")
DEFAULT_BACKEND = "http://localhost:8000"
DEFAULT_MODEL = "gemini-3.5-flash"

# Gemini 2.5 family uses integer thinking_budget rather than thinking_level.
# These mappings are deliberate: 0 disables thinking, 24576 is the documented
# max for Flash. Higher-budget calls don't always *use* the budget — Gemini's
# adaptive thinking only spends what it thinks the prompt warrants — which
# means Thinklet's "wasted HIGH" claim is sometimes about *budget allocated*
# rather than *budget burned*. Either is a valid cost-discipline story.
_LEVEL_TO_BUDGET: dict[str, int] = {
    "minimal": 0,
    "low": 1024,
    "medium": 4096,
    "high": 24576,
}


@dataclass
class ThinkletResponse:
    text: str
    span_id: Optional[str]
    thinking_level: str
    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: Optional[int]
    latency_ms: int
    estimated_cost_usd: Optional[float]
    source: str  # 'real' | 'demo'

    def __str__(self) -> str:
        return self.text


def _prompt_hash(model: str, prompt: str) -> str:
    # Retained for backward compat; new code should use hash_contents().
    h = hashlib.sha256(f"{model}|{prompt}".encode()).hexdigest()
    return h[:32]


def _estimate_input_tokens(contents_for_estimate: str) -> int:
    # Rough heuristic for demo mode: ~4 chars/token. For multimodal we
    # estimate against the redacted summary, which is good enough — real
    # mode reads the actual prompt_token_count from usage_metadata.
    return max(1, len(contents_for_estimate) // 4)


def _demo_response(prompt: str, level: str) -> tuple[str, int, int]:
    """Deterministic fake (response_text, output_tokens, thinking_tokens)."""
    seed = int(hashlib.sha256(f"{prompt}|{level}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    base_responses = [
        "Sure — here is a concise answer.",
        "Yes, that should work as expected.",
        "Result: 42",
        "ok",
        "Here is the requested summary in two lines.",
    ]
    text = rng.choice(base_responses)
    output_tokens = max(1, len(text) // 4)
    thinking = {"minimal": 0, "low": 180, "medium": 720, "high": 2800}[level]
    if thinking:
        thinking = int(thinking * rng.uniform(0.8, 1.2))
    return text, output_tokens, thinking


class ThinkletClient:
    def __init__(
        self,
        backend_url: Optional[str] = None,
        api_key: Optional[str] = None,
        demo_mode: Optional[bool] = None,
    ):
        self.backend_url = backend_url or os.environ.get(
            "THINKLET_BACKEND_URL", DEFAULT_BACKEND
        )
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if demo_mode is None:
            env = os.environ.get("THINKLET_DEMO_MODE", "").lower()
            demo_mode = env == "true"
        # Also force demo if no API key.
        self.demo_mode = bool(demo_mode or not self.api_key)
        self._http = httpx.Client(timeout=10.0)
        self._gemini = None
        if not self.demo_mode:
            try:
                from google import genai
                self._gemini = genai.Client(api_key=self.api_key)
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"Thinklet: Gemini init failed, demo mode: {exc}")
                self.demo_mode = True

    # ---- main entrypoint ----
    def call(
        self,
        prompt: Optional[str] = None,
        contents: Any = None,
        model: str = DEFAULT_MODEL,
        thinking_level: str = "medium",
        task_label: Optional[str] = None,
        trace_id: Optional[str] = None,
        call_id: Optional[str] = None,
    ) -> ThinkletResponse:
        """Make a Gemini call and capture it as a Thinklet span.

        Pass either `prompt=` (text-only) or `contents=` (multimodal Parts
        list — text + inline_data + file_data, same shape google-genai
        accepts). Exactly one must be provided.
        """
        if thinking_level not in THINKING_LEVELS:
            raise ValueError(
                f"thinking_level must be one of {THINKING_LEVELS}, got {thinking_level!r}"
            )
        if (prompt is None) == (contents is None):
            raise ValueError("Provide exactly one of prompt= or contents=")

        # Unified internal representation: always work via `contents`.
        contents_in = prompt if contents is None else contents
        is_multimodal = contents is not None and not (
            isinstance(contents, str)
            or (isinstance(contents, list) and all(isinstance(x, str) for x in contents))
        )

        prompt_hash = hash_contents(model, contents_in)
        redacted = redact_contents(contents_in)
        contents_json = serialize_contents(contents_in) if is_multimodal else None

        t0 = time.perf_counter()

        if self.demo_mode:
            text, out_tokens, thinking_tokens = _demo_response(redacted, thinking_level)
            input_tokens = _estimate_input_tokens(redacted)
            source = "demo"
        else:
            try:
                from google.genai import types
                from .contents import to_gemini_contents
                cfg = types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=_LEVEL_TO_BUDGET[thinking_level],
                        include_thoughts=False,
                    )
                )
                gemini_contents = (
                    to_gemini_contents(contents_json)
                    if contents_json is not None
                    else contents_in
                )
                resp = self._gemini.models.generate_content(
                    model=model, contents=gemini_contents, config=cfg,
                )
                text = (getattr(resp, "text", "") or "").strip()
                usage = getattr(resp, "usage_metadata", None)
                input_tokens = getattr(usage, "prompt_token_count", 0) or _estimate_input_tokens(redacted)
                out_tokens = getattr(usage, "candidates_token_count", 0) or max(1, len(text) // 4)
                thinking_tokens = getattr(usage, "thoughts_token_count", None)
                source = "real"
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"Thinklet: Gemini call failed, falling back to demo: {exc}")
                text, out_tokens, thinking_tokens = _demo_response(redacted, thinking_level)
                input_tokens = _estimate_input_tokens(redacted)
                source = "demo"

        latency_ms = int((time.perf_counter() - t0) * 1000)

        span_id = self._post_span(
            prompt=redacted,
            prompt_hash=prompt_hash,
            contents_json=contents_json,
            response_text=text,
            model=model,
            thinking_level=thinking_level,
            input_tokens=input_tokens,
            output_tokens=out_tokens,
            thinking_tokens=thinking_tokens,
            latency_ms=latency_ms,
            task_label=task_label,
            trace_id=trace_id,
            call_id=call_id,
            source=source,
        )

        return ThinkletResponse(
            text=text,
            span_id=span_id,
            thinking_level=thinking_level,
            model=model,
            input_tokens=input_tokens,
            output_tokens=out_tokens,
            thinking_tokens=thinking_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=None,
            source=source,
        )

    # ---- internal ----
    def _post_span(self, **kw) -> Optional[str]:
        payload: dict[str, Any] = {
            "prompt_hash": kw["prompt_hash"],
            "prompt_redacted": kw["prompt"],
            "response_redacted": kw["response_text"],
            "model": kw["model"],
            "thinking_level_used": kw["thinking_level"],
            "input_tokens": kw["input_tokens"],
            "output_tokens": kw["output_tokens"],
            "thinking_tokens": kw["thinking_tokens"],
            "latency_ms": kw["latency_ms"],
            "task_label": kw["task_label"],
            "trace_id": kw["trace_id"],
            "call_id": kw["call_id"],
            "source": kw["source"],
            "contents_json": kw.get("contents_json"),
        }
        try:
            r = self._http.post(f"{self.backend_url}/spans", json=payload)
            r.raise_for_status()
            return r.json().get("id")
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"Thinklet: span ingest failed (continuing): {exc}")
            return None

    def close(self) -> None:
        self._http.close()
