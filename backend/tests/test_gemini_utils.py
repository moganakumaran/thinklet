"""Tests for the 429 retry helper."""
from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    """Make retries effectively instantaneous for tests."""
    monkeypatch.setenv("THINKLET_RETRY_429_BASE_S", "0.001")
    monkeypatch.setenv("THINKLET_RETRY_429_CAP_S", "0.001")
    import importlib
    from backend.app import gemini_utils
    importlib.reload(gemini_utils)
    yield


def test_passes_through_on_first_try():
    from backend.app.gemini_utils import call_with_429_retry
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert call_with_429_retry(fn) == "ok"
    assert calls["n"] == 1


def test_reraises_non_429():
    from backend.app.gemini_utils import call_with_429_retry

    class Other(Exception):
        pass

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise Other("nope")

    with pytest.raises(Other):
        call_with_429_retry(fn)
    assert calls["n"] == 1  # not retried


def test_retries_on_429_then_succeeds():
    from backend.app.gemini_utils import call_with_429_retry
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED, retryDelay '0s'")
        return "ok"

    assert call_with_429_retry(fn, max_attempts=5) == "ok"
    assert calls["n"] == 3


def test_gives_up_after_max_attempts():
    from backend.app.gemini_utils import call_with_429_retry
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with pytest.raises(RuntimeError):
        call_with_429_retry(fn, max_attempts=2)
    assert calls["n"] == 2


def test_extract_retry_delay_from_message():
    from backend.app.gemini_utils import _extract_retry_delay_s
    msg = Exception("429 RESOURCE_EXHAUSTED ... 'retryDelay': '7s', ...")
    assert _extract_retry_delay_s(msg) == 7.0
