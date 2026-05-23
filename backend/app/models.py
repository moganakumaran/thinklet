"""Pydantic v2 models for Thinklet API.

Two layers:
  - Span/ReplayResult/JudgeResult: row-level shapes used by GET endpoints.
  - SpanIngest: the POST /spans payload (SDK-friendly, lenient on optional fields).
  - WasteReport/WasteMapCell: aggregate dashboard responses.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ThinkingLevel = Literal["minimal", "low", "medium", "high"]
Verdict = Literal["equivalent", "degraded", "materially_different", "uncertain"]
Source = Literal["real", "demo"]


class SpanIngest(BaseModel):
    """SDK-facing POST payload."""
    model_config = ConfigDict(extra="forbid")

    trace_id: Optional[str] = None
    call_id: Optional[str] = None
    prompt_hash: str
    prompt_redacted: Optional[str] = None
    response_redacted: Optional[str] = None
    model: str
    thinking_level_used: ThinkingLevel
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    thinking_tokens: Optional[int] = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    task_label: Optional[str] = None
    source: Source = "real"
    # Multimodal: serialized Gemini Parts list. None for text-only spans.
    contents_json: Optional[str] = None


class Span(BaseModel):
    id: str
    created_at: datetime
    trace_id: Optional[str] = None
    call_id: Optional[str] = None
    prompt_hash: str
    prompt_redacted: Optional[str] = None
    response_redacted: Optional[str] = None
    model: str
    thinking_level_used: ThinkingLevel
    input_tokens: int
    output_tokens: int
    thinking_tokens: Optional[int] = None
    total_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    task_label: Optional[str] = None
    source: Source
    is_multimodal: bool = False


class ReplayResult(BaseModel):
    id: str
    span_id: str
    target_thinking_level: ThinkingLevel
    response_redacted: Optional[str] = None
    input_tokens: int
    output_tokens: int
    thinking_tokens: Optional[int] = None
    latency_ms: int
    estimated_cost_usd: float
    created_at: datetime


class JudgeResult(BaseModel):
    id: str
    span_id: str
    replay_result_id: str
    original_level: ThinkingLevel
    alternative_level: ThinkingLevel
    verdict: Verdict
    confidence: float
    reasoning: Optional[str] = None
    votes: Optional[list[str]] = None
    recommended_level: Optional[ThinkingLevel] = None
    estimated_savings_usd: float
    created_at: datetime


class TopWastePattern(BaseModel):
    task_label: Optional[str]
    calls_with_waste: int
    estimated_savings_usd: float
    typical_original_level: ThinkingLevel
    typical_recommended_level: ThinkingLevel


class RecommendedDowngrade(BaseModel):
    from_level: ThinkingLevel
    to_level: ThinkingLevel
    affected_calls: int
    estimated_savings_usd: float


class WasteReport(BaseModel):
    total_calls_audited: int
    calls_with_likely_waste: int
    estimated_cost_wasted_usd: float
    monthly_projection_usd: float
    observed_days: float
    top_wasteful_patterns: list[TopWastePattern]
    recommended_downgrades: list[RecommendedDowngrade]
    demo_mode: bool


class WasteMapCell(BaseModel):
    task_label: str
    prompt_hash: str
    original_level: ThinkingLevel
    recommended_level: Optional[ThinkingLevel] = None
    verdict: Verdict
    color: Literal["red", "yellow", "green"]
    span_count: int
    estimated_savings_usd: float
    # Sample-size aware confidence: how many of the `span_count` audited
    # samples had a safe downgrade. equivalent_rate = count / span_count.
    equivalent_sample_count: int = 0
    equivalent_rate: float = 0.0


class SpanDetail(BaseModel):
    span: Span
    replays: list[ReplayResult]
    judges: list[JudgeResult]


class CellSampleSummary(BaseModel):
    """One row in a cell's audit-history list."""
    span_id: str
    created_at: datetime
    thinking_tokens: Optional[int] = None
    estimated_cost_usd: float
    best_verdict: Optional[Verdict] = None
    best_alternative_level: Optional[ThinkingLevel] = None
    best_savings_usd: float = 0.0


class CellHistory(BaseModel):
    """Audit history for one (task_label, prompt_hash, original_level) cell."""
    task_label: str
    prompt_hash: str
    original_level: ThinkingLevel
    sample_count: int
    samples: list[CellSampleSummary]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    demo_mode: bool
    db_path: str
    span_count: int
