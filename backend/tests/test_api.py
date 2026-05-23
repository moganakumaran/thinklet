"""Phase 2 API tests against a fresh in-memory-ish seeded DB.

We use a tmp file (not :memory:) because seed.generate_demo_data uses
multi-statement SQL via app.state.con, and DuckDB file mode is the actual
production path.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("thinklet") / "test.duckdb"
    os.environ["THINKLET_DB_PATH"] = str(db_path)
    os.environ["THINKLET_DEMO_MODE"] = "true"

    # Seed before the app starts so /health reflects seeded data.
    from backend.app.db import connect
    from backend.app.seed import generate_demo_data
    con = connect(str(db_path))
    generate_demo_data(con)
    con.close()

    from backend.app.main import app
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True
    assert body["span_count"] == 120


def test_post_and_get_spans(client):
    payload = {
        "prompt_hash": "abc123",
        "model": "gemini-2.5-flash",
        "thinking_level_used": "high",
        "input_tokens": 10,
        "output_tokens": 20,
        "thinking_tokens": 500,
        "latency_ms": 600,
        "task_label": "test",
        "source": "real",
    }
    r = client.post("/spans", json=payload)
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]
    assert r.json()["estimated_cost_usd"] > 0

    r = client.get("/spans", params={"limit": 5})
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert new_id in ids


def test_waste_report_shape(client):
    r = client.get("/waste-report")
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls_audited"] >= 120
    assert body["calls_with_likely_waste"] > 0
    assert body["estimated_cost_wasted_usd"] > 0
    assert body["monthly_projection_usd"] > 0
    assert len(body["top_wasteful_patterns"]) >= 1
    assert len(body["recommended_downgrades"]) >= 1


def test_waste_map_shape(client):
    r = client.get("/waste-map")
    assert r.status_code == 200
    cells = r.json()
    assert len(cells) >= 4  # at least one cell per planted pattern
    colors = {c["color"] for c in cells}
    assert "red" in colors
    assert "green" in colors


def test_span_detail(client):
    spans = client.get("/spans", params={"limit": 1}).json()
    assert spans
    span_id = spans[0]["id"]
    r = client.get(f"/spans/{span_id}/detail")
    assert r.status_code == 200
    body = r.json()
    assert body["span"]["id"] == span_id
