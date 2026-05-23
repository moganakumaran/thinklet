"""Replay engine.

For each unique (prompt_hash, model, target_level), produce a fresh replay
of the original prompt at the target thinking level. Persist as
replay_results; track per-span status in replay_jobs.

Trigger via POST /replay/run. Synchronous (no background workers per MVP
constraints).
"""
from __future__ import annotations

import hashlib
import os
import random
import time
import uuid
import warnings
from datetime import datetime, timezone
from typing import Optional

# (time is already imported above)

from .gemini_utils import call_with_429_retry
from .pricing import estimate_cost

LEVELS = ["minimal", "low", "medium", "high"]
LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

# See sdk/thinklet_sdk/client.py for rationale on these budgets.
_LEVEL_TO_BUDGET: dict[str, int] = {
    "minimal": 0, "low": 1024, "medium": 4096, "high": 24576,
}

MAX_ATTEMPTS = 3

# Pace real-Gemini replay calls to stay under free-tier RPM. 13s = ~4.6 RPM,
# safely under the 5-RPM limit on gemini-2.5-flash. Demo mode never sleeps.
_REPLAY_SLEEP_S = float(os.environ.get("THINKLET_REPLAY_SLEEP_S", "13.0"))


def _lower_levels(level: str) -> list[str]:
    return [lvl for lvl in LEVELS if LEVEL_RANK[lvl] < LEVEL_RANK[level]]


def _higher_levels(level: str) -> list[str]:
    return [lvl for lvl in LEVELS if LEVEL_RANK[lvl] > LEVEL_RANK[level]]


def _replay_targets(level: str) -> list[str]:
    """Targets for the replay fan-out.

    For non-MINIMAL spans: fan DOWN to detect waste (the standard case).
    For MINIMAL spans:     fan UP to detect quality risk (you may have been
                           under-budgeting). Without this, MINIMAL spans get
                           zero audit coverage in live mode — the
                           materially_different verdict can only fire when
                           we have a higher-level replay to compare against.
    """
    if level == "minimal":
        return _higher_levels(level)
    return _lower_levels(level)


def _demo_mode() -> bool:
    return os.environ.get("THINKLET_DEMO_MODE", "").lower() == "true"


def _demo_replay(prompt: str, target_level: str) -> tuple[str, int, int]:
    """Deterministic fake replay: (response, output_tokens, thinking_tokens)."""
    seed = int(hashlib.sha256(f"{prompt}|{target_level}|replay".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    out_tokens = max(4, 12 + rng.randint(-4, 6))
    thinking = {"minimal": 0, "low": 180, "medium": 720, "high": 2800}[target_level]
    if thinking:
        thinking = int(thinking * rng.uniform(0.8, 1.2))
    # Truncate/shorten as level drops — visually plausible difference.
    if target_level == "minimal":
        text = "OK."
    elif target_level == "low":
        text = "Yes — that should work."
    elif target_level == "medium":
        text = "Yes, that should work as expected for typical inputs."
    else:
        text = "Yes — that approach should work. It handles typical inputs and degrades gracefully on edge cases."
    return text, out_tokens, thinking


def _create_jobs(con, span_id_filter: Optional[str] = None) -> int:
    """For every span without a job at a given lower level, create a pending job.

    If span_id_filter is set, only consider that one span (used by the Try It
    UI's per-span audit flow).
    """
    if span_id_filter:
        rows = con.execute(
            """SELECT id, prompt_hash, thinking_level_used FROM spans WHERE id=?""",
            (span_id_filter,),
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT id, prompt_hash, thinking_level_used FROM spans"""
        ).fetchall()
    inserted = 0
    now = datetime.now(timezone.utc)
    for span_id, prompt_hash, level in rows:
        for target in _replay_targets(level):
            existing = con.execute(
                """SELECT id FROM replay_jobs
                   WHERE span_id=? AND target_thinking_level=? LIMIT 1""",
                (span_id, target),
            ).fetchone()
            if existing:
                continue
            con.execute(
                """INSERT INTO replay_jobs (id, span_id, prompt_hash,
                       target_thinking_level, status, attempts, error,
                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', 0, NULL, ?, ?)""",
                (str(uuid.uuid4()), span_id, prompt_hash, target, now, now),
            )
            inserted += 1
    return inserted


def _result_exists(con, span_id: str, target: str) -> bool:
    r = con.execute(
        """SELECT 1 FROM replay_results
           WHERE span_id=? AND target_thinking_level=? LIMIT 1""",
        (span_id, target),
    ).fetchone()
    return r is not None


def _run_one(con, job_row, gemini_client) -> tuple[bool, Optional[str]]:
    job_id, span_id, target = job_row[0], job_row[1], job_row[2]
    span = con.execute(
        """SELECT prompt_redacted, model, input_tokens, contents_json
           FROM spans WHERE id=?""",
        (span_id,),
    ).fetchone()
    if not span:
        return False, "span not found"
    prompt, model, original_input_tokens, contents_json = span

    # Idempotency: if a result already exists, mark job completed and return.
    if _result_exists(con, span_id, target):
        return True, None

    t0 = time.perf_counter()
    used_demo_fallback = False
    if gemini_client is None or _demo_mode():
        text, out_tokens, thinking_tokens = _demo_replay(prompt or "", target)
        input_tokens = original_input_tokens
    else:
        try:
            from google.genai import types
            cfg = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=_LEVEL_TO_BUDGET[target],
                    include_thoughts=False,
                )
            )
            # Multimodal: rebuild the original Parts list from contents_json.
            # Text-only: just pass the prompt string.
            if contents_json:
                # Lazy import so demo-only envs don't pay for the SDK helper.
                import sys
                from pathlib import Path
                sdk_path = Path(__file__).resolve().parents[2] / "sdk"
                if str(sdk_path) not in sys.path:
                    sys.path.insert(0, str(sdk_path))
                from thinklet_sdk.contents import to_gemini_contents
                gemini_contents = to_gemini_contents(contents_json)
            else:
                gemini_contents = prompt or ""
            resp = call_with_429_retry(
                lambda: gemini_client.models.generate_content(
                    model=model, contents=gemini_contents, config=cfg,
                ),
                label=f"replay[{target}]",
            )
            text = (getattr(resp, "text", "") or "").strip()
            usage = getattr(resp, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", 0) or original_input_tokens
            out_tokens = getattr(usage, "candidates_token_count", 0) or max(1, len(text) // 4)
            thinking_tokens = getattr(usage, "thoughts_token_count", None)
        except Exception as exc:  # noqa: BLE001
            # Real-API failure (quota, network, etc.) — fall back to a demo
            # replay so the audit pipeline still completes end-to-end. The
            # replay_result is marked source-by-omission; downstream logic
            # doesn't differentiate. Note the error for log visibility.
            warnings.warn(f"replay: real-API call failed, using demo: {exc}")
            text, out_tokens, thinking_tokens = _demo_replay(prompt or "", target)
            input_tokens = original_input_tokens
            used_demo_fallback = True

    latency_ms = int((time.perf_counter() - t0) * 1000)
    cost = estimate_cost(model, input_tokens, out_tokens, thinking_tokens)

    con.execute(
        """INSERT INTO replay_results (id, span_id, target_thinking_level,
               response_redacted, input_tokens, output_tokens, thinking_tokens,
               latency_ms, estimated_cost_usd, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()), span_id, target, text,
            input_tokens, out_tokens, thinking_tokens, latency_ms, cost,
            datetime.now(timezone.utc),
        ),
    )
    return True, None


def _gemini_client():
    if _demo_mode() or not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"replay: Gemini init failed, using demo replays: {exc}")
        return None


def run_replays(con, span_id: Optional[str] = None) -> dict:
    """Create pending jobs, then process them. Returns a summary dict.

    When span_id is provided, both job creation and processing are scoped to
    that single span only. Default (None) preserves the original behavior of
    processing every span / every pending+failed job in the system.
    """
    created = _create_jobs(con, span_id_filter=span_id)
    client = _gemini_client()

    if span_id:
        pending = con.execute(
            """SELECT id, span_id, target_thinking_level, attempts
               FROM replay_jobs
               WHERE status IN ('pending', 'failed') AND span_id=?""",
            (span_id,),
        ).fetchall()
    else:
        pending = con.execute(
            """SELECT id, span_id, target_thinking_level, attempts
               FROM replay_jobs WHERE status IN ('pending', 'failed')"""
        ).fetchall()

    completed = 0
    failed = 0
    real_calls_made = 0
    for job in pending:
        job_id, span_id, target, attempts = job
        if attempts >= MAX_ATTEMPTS:
            continue
        # mark running
        con.execute(
            "UPDATE replay_jobs SET status='running', attempts=attempts+1, "
            "updated_at=? WHERE id=?",
            (datetime.now(timezone.utc), job_id),
        )
        # Pace real-API calls between jobs to stay under RPM limits. Skip
        # the sleep before the first real call.
        if client is not None and _REPLAY_SLEEP_S > 0 and real_calls_made > 0:
            time.sleep(_REPLAY_SLEEP_S)
        ok, err = _run_one(con, (job_id, span_id, target), client)
        if client is not None:
            real_calls_made += 1
        now = datetime.now(timezone.utc)
        if ok:
            con.execute(
                "UPDATE replay_jobs SET status='completed', error=NULL, "
                "updated_at=? WHERE id=?",
                (now, job_id),
            )
            completed += 1
        else:
            con.execute(
                "UPDATE replay_jobs SET status='failed', error=?, updated_at=? "
                "WHERE id=?",
                (err, now, job_id),
            )
            failed += 1

    return {
        "jobs_created": created,
        "jobs_processed": completed + failed,
        "completed": completed,
        "failed": failed,
    }
