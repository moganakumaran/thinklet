"""Span ingest helpers. Pure functions over a DuckDB connection."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .models import Span, SpanIngest
from .pricing import estimate_cost


def insert_span(con, payload: SpanIngest) -> Span:
    span_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    cost = estimate_cost(
        payload.model,
        payload.input_tokens,
        payload.output_tokens,
        payload.thinking_tokens,
    )
    total = payload.input_tokens + payload.output_tokens + (payload.thinking_tokens or 0)
    con.execute(
        """
        INSERT INTO spans (id, created_at, trace_id, call_id, prompt_hash,
            prompt_redacted, response_redacted, model, thinking_level_used,
            input_tokens, output_tokens, thinking_tokens, total_tokens,
            latency_ms, estimated_cost_usd, task_label, source, contents_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            span_id,
            created_at,
            payload.trace_id,
            payload.call_id,
            payload.prompt_hash,
            payload.prompt_redacted,
            payload.response_redacted,
            payload.model,
            payload.thinking_level_used,
            payload.input_tokens,
            payload.output_tokens,
            payload.thinking_tokens,
            total,
            payload.latency_ms,
            cost,
            payload.task_label,
            payload.source,
            payload.contents_json,
        ),
    )
    return Span(
        id=span_id,
        created_at=created_at,
        trace_id=payload.trace_id,
        call_id=payload.call_id,
        prompt_hash=payload.prompt_hash,
        prompt_redacted=payload.prompt_redacted,
        response_redacted=payload.response_redacted,
        model=payload.model,
        thinking_level_used=payload.thinking_level_used,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        thinking_tokens=payload.thinking_tokens,
        total_tokens=total,
        latency_ms=payload.latency_ms,
        estimated_cost_usd=cost,
        task_label=payload.task_label,
        source=payload.source,
        is_multimodal=payload.contents_json is not None,
    )


def _votes_loads(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
