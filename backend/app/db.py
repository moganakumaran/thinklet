"""DuckDB connection helper + schema bootstrap.

Single-file local DB at data/thinklet.duckdb (path overridable via
THINKLET_DB_PATH env var). Schema is idempotent — safe to call on every
process start.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import duckdb

DEFAULT_DB_PATH = "data/thinklet.duckdb"


def _resolve_db_path() -> Path:
    raw = os.environ.get("THINKLET_DB_PATH", DEFAULT_DB_PATH)
    p = Path(raw)
    if not p.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        p = repo_root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect(db_path: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. Each call returns a fresh handle.

    DuckDB allows multiple read-only connections to the same file but only
    one writable connection process-wide. For our MVP that's fine — the
    FastAPI process holds the writer, seed scripts run before the server.
    """
    path = Path(db_path) if db_path else _resolve_db_path()
    con = duckdb.connect(str(path))
    bootstrap(con)
    return con


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spans (
    id                    VARCHAR PRIMARY KEY,
    created_at            TIMESTAMP NOT NULL,
    trace_id              VARCHAR,
    call_id               VARCHAR,
    prompt_hash           VARCHAR NOT NULL,
    prompt_redacted       VARCHAR,
    response_redacted     VARCHAR,
    model                 VARCHAR NOT NULL,
    thinking_level_used   VARCHAR NOT NULL,
    input_tokens          INTEGER NOT NULL,
    output_tokens         INTEGER NOT NULL,
    thinking_tokens       INTEGER,
    total_tokens          INTEGER NOT NULL,
    latency_ms            INTEGER NOT NULL,
    estimated_cost_usd    DOUBLE NOT NULL,
    task_label            VARCHAR,
    source                VARCHAR NOT NULL  -- 'real' | 'demo'
);

CREATE TABLE IF NOT EXISTS replay_jobs (
    id                       VARCHAR PRIMARY KEY,
    span_id                  VARCHAR NOT NULL,
    prompt_hash              VARCHAR NOT NULL,
    target_thinking_level    VARCHAR NOT NULL,
    status                   VARCHAR NOT NULL,  -- pending|running|completed|failed
    attempts                 INTEGER NOT NULL DEFAULT 0,
    error                    VARCHAR,
    created_at               TIMESTAMP NOT NULL,
    updated_at               TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS replay_results (
    id                       VARCHAR PRIMARY KEY,
    span_id                  VARCHAR NOT NULL,
    target_thinking_level    VARCHAR NOT NULL,
    response_redacted        VARCHAR,
    input_tokens             INTEGER NOT NULL,
    output_tokens            INTEGER NOT NULL,
    thinking_tokens          INTEGER,
    latency_ms               INTEGER NOT NULL,
    estimated_cost_usd       DOUBLE NOT NULL,
    created_at               TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_results (
    id                       VARCHAR PRIMARY KEY,
    span_id                  VARCHAR NOT NULL,
    replay_result_id         VARCHAR NOT NULL,
    original_level           VARCHAR NOT NULL,
    alternative_level        VARCHAR NOT NULL,
    verdict                  VARCHAR NOT NULL,  -- equivalent|degraded|materially_different|uncertain
    confidence               DOUBLE NOT NULL,
    reasoning                VARCHAR,
    votes_json               VARCHAR,
    recommended_level        VARCHAR,
    estimated_savings_usd    DOUBLE NOT NULL DEFAULT 0,
    created_at               TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spans_prompt_hash ON spans(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_spans_created_at ON spans(created_at);
CREATE INDEX IF NOT EXISTS idx_replay_jobs_span ON replay_jobs(span_id);
CREATE INDEX IF NOT EXISTS idx_replay_results_span ON replay_results(span_id);
CREATE INDEX IF NOT EXISTS idx_judge_results_span ON judge_results(span_id);
"""


def bootstrap(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables if missing. Safe to call repeatedly."""
    con.execute(SCHEMA_SQL)
    _migrate(con)


def _migrate(con: duckdb.DuckDBPyConnection) -> None:
    """Idempotent schema migrations. Each block must be safe to run on
    any prior schema version."""
    # v2: contents_json holds serialized Gemini Parts list for multimodal
    # spans (text + inline_data + file_data). NULL for text-only calls.
    con.execute("ALTER TABLE spans ADD COLUMN IF NOT EXISTS contents_json VARCHAR")
