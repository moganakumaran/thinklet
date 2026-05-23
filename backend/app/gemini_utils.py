"""Shared Gemini-call helpers — retry/backoff on rate-limit errors."""
from __future__ import annotations

import os
import re
import time
import warnings
from typing import Any, Callable

# Inner retry budget when a single call hits 429 RESOURCE_EXHAUSTED. This is
# separate from the per-job MAX_ATTEMPTS counter — it absorbs transient quota
# dips inside one logical call instead of marking the job failed.
_RETRY_429_MAX_ATTEMPTS = int(os.environ.get("THINKLET_RETRY_429_MAX_ATTEMPTS", "3"))
# Base sleep for backoff. We prefer the API's retry_delay when it's present.
_RETRY_429_BASE_S = float(os.environ.get("THINKLET_RETRY_429_BASE_S", "12.0"))
_RETRY_429_CAP_S = float(os.environ.get("THINKLET_RETRY_429_CAP_S", "60.0"))


def _is_429(exc: Exception) -> bool:
    name = type(exc).__name__
    text = str(exc)
    return (
        "429" in text
        or "RESOURCE_EXHAUSTED" in text
        or name == "ResourceExhausted"
        or "Quota exceeded" in text
    )


_RETRY_DELAY_RE = re.compile(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s?['\"]")


def _extract_retry_delay_s(exc: Exception) -> float | None:
    """Pull `retryDelay: "31s"` out of a Google API error message if present."""
    m = _RETRY_DELAY_RE.search(str(exc))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def call_with_429_retry(
    fn: Callable[[], Any],
    *,
    label: str = "gemini",
    max_attempts: int | None = None,
) -> Any:
    """Invoke `fn()` and retry on RESOURCE_EXHAUSTED with exponential backoff.

    For non-429 errors, re-raises immediately. For 429s, sleeps for either the
    server-reported `retryDelay` or an exponential backoff (12s, 24s, 48s,
    capped at 60s), then retries up to `max_attempts` times.
    """
    attempts = max_attempts or _RETRY_429_MAX_ATTEMPTS
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not _is_429(exc):
                raise
            last_exc = exc
            if attempt >= attempts:
                break
            server_delay = _extract_retry_delay_s(exc)
            backoff = min(_RETRY_429_BASE_S * (2 ** (attempt - 1)), _RETRY_429_CAP_S)
            sleep_s = max(server_delay or 0, backoff)
            warnings.warn(
                f"{label}: 429 attempt {attempt}/{attempts}, "
                f"sleeping {sleep_s:.1f}s (server retry_delay={server_delay})"
            )
            time.sleep(sleep_s)
    # Exhausted: re-raise the last seen exception.
    assert last_exc is not None
    raise last_exc
