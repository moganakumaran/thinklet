"""Phase 4 replay engine tests."""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "replay.duckdb"
    os.environ["THINKLET_DB_PATH"] = str(db_path)
    os.environ["THINKLET_DEMO_MODE"] = "true"
    from backend.app.db import connect
    con = connect(str(db_path))
    yield con
    con.close()


def _ingest_span(con, level, prompt_hash="rep-hash", task="rep_test"):
    from datetime import datetime, timezone
    import uuid
    span_id = str(uuid.uuid4())
    con.execute(
        """INSERT INTO spans (id, created_at, prompt_hash, prompt_redacted,
              response_redacted, model, thinking_level_used, input_tokens,
              output_tokens, thinking_tokens, total_tokens, latency_ms,
              estimated_cost_usd, task_label, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            span_id, datetime.now(timezone.utc),
            prompt_hash, "Test prompt for replay.", "Test response.",
            "gemini-2.5-flash", level,
            20, 30, 1000 if level == "high" else 0,
            20 + 30 + (1000 if level == "high" else 0),
            500, 0.001, task, "real",
        ),
    )
    return span_id


def test_replay_creates_jobs_and_results_for_high(fresh_db):
    from backend.app.replay import run_replays
    span_id = _ingest_span(fresh_db, "high")
    result = run_replays(fresh_db)
    # HIGH -> MEDIUM, LOW, MINIMAL = 3 jobs
    assert result["jobs_created"] == 3
    assert result["completed"] == 3
    assert result["failed"] == 0

    rows = fresh_db.execute(
        "SELECT target_thinking_level FROM replay_results WHERE span_id=? ORDER BY target_thinking_level",
        (span_id,),
    ).fetchall()
    targets = sorted(r[0] for r in rows)
    assert targets == ["low", "medium", "minimal"]


def test_replay_fans_up_from_minimal(fresh_db):
    """MINIMAL spans fan UPWARD to higher levels so we can detect quality risk
    (the user may have been under-budgeting). This is the inverse of waste
    detection — we replay at MORE thinking to see if the original answer was
    materially worse than what HIGH would have produced."""
    from backend.app.replay import run_replays
    span_id = _ingest_span(fresh_db, "minimal", prompt_hash="min-hash")
    result = run_replays(fresh_db)
    # MINIMAL -> LOW, MEDIUM, HIGH = 3 jobs (upward).
    assert result["jobs_created"] == 3
    assert result["completed"] == 3
    rows = fresh_db.execute(
        "SELECT target_thinking_level FROM replay_results WHERE span_id=? "
        "ORDER BY target_thinking_level",
        (span_id,),
    ).fetchall()
    assert sorted(r[0] for r in rows) == ["high", "low", "medium"]


def test_replay_scoped_to_span_id(fresh_db):
    """When span_id is set, only that span's replays are created/processed."""
    from backend.app.replay import run_replays
    span_a = _ingest_span(fresh_db, "high", prompt_hash="A")
    _span_b = _ingest_span(fresh_db, "high", prompt_hash="B")

    result = run_replays(fresh_db, span_id=span_a)
    assert result["jobs_created"] == 3   # only span_a fanned out
    assert result["completed"] == 3
    # span_b should have NO replay jobs at all.
    rows = fresh_db.execute(
        "SELECT COUNT(*) FROM replay_jobs WHERE span_id != ?", (span_a,)
    ).fetchone()
    assert rows[0] == 0


def test_replay_is_idempotent(fresh_db):
    from backend.app.replay import run_replays
    span_id = _ingest_span(fresh_db, "medium", prompt_hash="med-hash")

    first = run_replays(fresh_db)
    second = run_replays(fresh_db)

    # MEDIUM -> LOW, MINIMAL = 2 jobs the first time.
    assert first["jobs_created"] == 2
    assert first["completed"] == 2
    # Second run creates no new jobs and processes none.
    assert second["jobs_created"] == 0
    assert second["jobs_processed"] == 0
    # Replay results still only 2 (no duplicates).
    count = fresh_db.execute(
        "SELECT COUNT(*) FROM replay_results WHERE span_id=?", (span_id,)
    ).fetchone()[0]
    assert count == 2
