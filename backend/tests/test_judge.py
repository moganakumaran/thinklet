"""Phase 5 judge tests."""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "judge.duckdb"
    os.environ["THINKLET_DB_PATH"] = str(db_path)
    os.environ["THINKLET_DEMO_MODE"] = "true"
    from backend.app.db import connect
    con = connect(str(db_path))
    yield con
    con.close()


def test_deterministic_exact_match():
    from backend.app.judge import deterministic_verdict
    assert deterministic_verdict("Hello", "Hello") == "equivalent"
    assert deterministic_verdict("Hello", "  hello  ") == "equivalent"


def test_deterministic_json_equal():
    from backend.app.judge import deterministic_verdict
    assert deterministic_verdict('{"a": 1}', '{ "a": 1 }') == "equivalent"


def test_deterministic_numeric():
    from backend.app.judge import deterministic_verdict
    assert deterministic_verdict("Answer: 42", "The result is 42.") == "equivalent"


def test_deterministic_no_match():
    from backend.app.judge import deterministic_verdict
    assert deterministic_verdict("hello world", "totally different stuff") is None


def _seed_pair(con, orig_resp, replay_resp, orig_level="high", alt_level="minimal",
               orig_cost=0.01, replay_cost=0.0001):
    from datetime import datetime, timezone
    import uuid
    span_id = str(uuid.uuid4())
    replay_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    con.execute(
        """INSERT INTO spans (id, created_at, prompt_hash, prompt_redacted,
              response_redacted, model, thinking_level_used, input_tokens,
              output_tokens, thinking_tokens, total_tokens, latency_ms,
              estimated_cost_usd, task_label, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (span_id, now, "h", "Original prompt.", orig_resp,
         "gemini-2.5-flash", orig_level, 10, 20, 1000, 1030, 500, orig_cost,
         "t", "real"),
    )
    con.execute(
        """INSERT INTO replay_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (replay_id, span_id, alt_level, replay_resp, 10, 20, 0, 200, replay_cost, now),
    )
    return span_id, replay_id


def test_judge_equivalent_via_deterministic(fresh_db):
    from backend.app.judge import run_judges
    _seed_pair(fresh_db, "Same answer.", "same answer.")
    summary = run_judges(fresh_db)
    assert summary["judged"] == 1
    row = fresh_db.execute(
        "SELECT verdict, estimated_savings_usd FROM judge_results"
    ).fetchone()
    assert row[0] == "equivalent"
    assert row[1] > 0  # savings paid


def test_judge_is_idempotent(fresh_db):
    from backend.app.judge import run_judges
    _seed_pair(fresh_db, "A", "A")
    run_judges(fresh_db)
    second = run_judges(fresh_db)
    assert second["judged"] == 0
    assert second["skipped_existing"] == 1


def test_judge_scoped_to_span_id(fresh_db):
    """When span_id is set, only that span's replays are judged."""
    from backend.app.judge import run_judges
    span_a, _ = _seed_pair(fresh_db, "Same.", "same.")
    span_b, _ = _seed_pair(fresh_db, "Different.", "completely different.",
                           orig_level="medium", alt_level="low")

    summary = run_judges(fresh_db, span_id=span_a)
    assert summary["judged"] == 1
    # Only span_a should have a judge_result row.
    n_a = fresh_db.execute(
        "SELECT COUNT(*) FROM judge_results WHERE span_id=?", (span_a,)
    ).fetchone()[0]
    n_b = fresh_db.execute(
        "SELECT COUNT(*) FROM judge_results WHERE span_id=?", (span_b,)
    ).fetchone()[0]
    assert n_a == 1
    assert n_b == 0


def test_judge_low_overlap_demo_falls_to_degraded_or_uncertain(fresh_db):
    """Demo heuristic: low token overlap -> not equivalent, no savings."""
    from backend.app.judge import run_judges
    _seed_pair(
        fresh_db,
        "Detailed explanation of root cause and a multi-step fix proposal "
        "with rationale and test plan.",
        "ok",
    )
    run_judges(fresh_db)
    row = fresh_db.execute(
        "SELECT verdict, estimated_savings_usd FROM judge_results"
    ).fetchone()
    assert row[0] in ("degraded", "uncertain", "materially_different")
    assert row[1] == 0.0
