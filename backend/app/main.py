"""FastAPI app for Thinklet.

Endpoints:
  GET  /health
  POST /spans
  GET  /spans
  GET  /spans/{span_id}/detail
  GET  /waste-report
  GET  /waste-map
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .db import _resolve_db_path, connect
from .ingest import _votes_loads, insert_span
from .judge import run_judges
from .replay import run_replays
from .models import (
    CellHistory,
    CellSampleSummary,
    HealthResponse,
    JudgeResult,
    RecommendedDowngrade,
    ReplayResult,
    Span,
    SpanDetail,
    SpanIngest,
    TopWastePattern,
    WasteMapCell,
    WasteReport,
)

LEVELS = ["minimal", "low", "medium", "high"]
LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Single shared connection for the process.
    app.state.con = connect()
    try:
        yield
    finally:
        app.state.con.close()


app = FastAPI(title="Thinklet", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _demo_mode() -> bool:
    return os.environ.get("THINKLET_DEMO_MODE", "").lower() == "true"


# ---------------- helpers ----------------

def _row_to_span(row) -> Span:
    return Span(
        id=row[0],
        created_at=row[1],
        trace_id=row[2],
        call_id=row[3],
        prompt_hash=row[4],
        prompt_redacted=row[5],
        response_redacted=row[6],
        model=row[7],
        thinking_level_used=row[8],
        input_tokens=row[9],
        output_tokens=row[10],
        thinking_tokens=row[11],
        total_tokens=row[12],
        latency_ms=row[13],
        estimated_cost_usd=row[14],
        task_label=row[15],
        source=row[16],
        is_multimodal=row[17] is not None,
    )


SPAN_COLS = (
    "id, created_at, trace_id, call_id, prompt_hash, prompt_redacted, "
    "response_redacted, model, thinking_level_used, input_tokens, "
    "output_tokens, thinking_tokens, total_tokens, latency_ms, "
    "estimated_cost_usd, task_label, source, contents_json"
)


# ---------------- routes ----------------

@app.get("/health", response_model=HealthResponse)
def health():
    con = app.state.con.cursor()
    n = con.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
    return HealthResponse(
        status="ok",
        demo_mode=_demo_mode(),
        db_path=str(_resolve_db_path()),
        span_count=n,
    )


@app.post("/replay/run")
def replay_run():
    return run_replays(app.state.con.cursor())


@app.post("/judge/run")
def judge_run():
    return run_judges(app.state.con.cursor())


# ---------------- audit (interactive Try It flow) ----------------

@app.post("/audit/capture", response_model=Span)
async def audit_capture(
    prompt: str = Form(...),
    task_label: str = Form("try_it"),
    thinking_level: str = Form("high"),
    model: str = Form("gemini-3.5-flash"),
    image: Optional[UploadFile] = File(None),
):
    """Capture a single Gemini call as a Thinklet span.

    Calls Gemini (or demo fallback) inline, then inserts the span directly —
    no SDK loopback HTTP. The SDK helpers (hash, redact, serialize) are still
    reused for consistency with script-driven captures.
    """
    if thinking_level not in ("minimal", "low", "medium", "high"):
        raise HTTPException(status_code=400, detail="invalid thinking_level")

    # Lazy-import SDK helpers (hash / redact / serialize) without instantiating
    # the HTTP-loopback ThinkletClient.
    import sys
    from pathlib import Path
    sdk_path = Path(__file__).resolve().parents[2] / "sdk"
    if str(sdk_path) not in sys.path:
        sys.path.insert(0, str(sdk_path))
    from thinklet_sdk.contents import (  # noqa: E402
        hash_contents, redact_contents, serialize_contents, normalize_contents,
    )

    contents_in: object
    is_multimodal = False
    if image is not None:
        data = await image.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty image upload")
        if len(data) > 4 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="image too large (>4MB)")
        contents_in = [
            {"text": prompt},
            {"inline_data": {
                "mime_type": image.content_type or "application/octet-stream",
                "data": data,
            }},
        ]
        is_multimodal = True
    else:
        contents_in = prompt

    prompt_hash = hash_contents(model, contents_in)
    redacted = redact_contents(contents_in)
    contents_json = serialize_contents(contents_in) if is_multimodal else None

    # --- call Gemini (or fall back to demo response) ---
    import time as _time
    demo_mode = os.environ.get("THINKLET_DEMO_MODE", "").lower() == "true"
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        demo_mode = True

    _LEVEL_TO_BUDGET = {"minimal": 0, "low": 1024, "medium": 4096, "high": 24576}
    text = ""
    input_tokens = max(1, len(redacted) // 4)
    output_tokens = 1
    thinking_tokens: Optional[int] = None
    latency_ms = 0
    source = "demo"
    t0 = _time.perf_counter()
    if not demo_mode:
        try:
            from google import genai
            from google.genai import types
            from thinklet_sdk.contents import to_gemini_contents
            client = genai.Client(api_key=api_key)
            cfg = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=_LEVEL_TO_BUDGET[thinking_level],
                    include_thoughts=False,
                )
            )
            gemini_contents = (
                to_gemini_contents(contents_json)
                if contents_json
                else (prompt if isinstance(contents_in, str) else contents_in)
            )
            resp = client.models.generate_content(
                model=model, contents=gemini_contents, config=cfg,
            )
            text = (getattr(resp, "text", "") or "").strip()
            usage = getattr(resp, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", 0) or input_tokens
            output_tokens = getattr(usage, "candidates_token_count", 0) or max(1, len(text) // 4)
            thinking_tokens = getattr(usage, "thoughts_token_count", None)
            source = "real"
        except Exception as exc:  # noqa: BLE001
            # Quota exhaustion or any other Gemini failure falls back cleanly.
            text = f"[demo fallback: {type(exc).__name__}] Reply at {thinking_level}."
            output_tokens = max(1, len(text) // 4)
            thinking_tokens = {"minimal": 0, "low": 180, "medium": 720, "high": 2800}[thinking_level]
            source = "demo"
    else:
        text = f"[demo] response at {thinking_level} for {redacted[:40]}"
        output_tokens = max(1, len(text) // 4)
        thinking_tokens = {"minimal": 0, "low": 180, "medium": 720, "high": 2800}[thinking_level]

    latency_ms = int((_time.perf_counter() - t0) * 1000)

    payload = SpanIngest(
        prompt_hash=prompt_hash,
        prompt_redacted=redacted,
        response_redacted=text,
        model=model,
        thinking_level_used=thinking_level,  # type: ignore[arg-type]
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        thinking_tokens=thinking_tokens,
        latency_ms=latency_ms,
        task_label=task_label,
        source=source,  # type: ignore[arg-type]
        contents_json=contents_json,
    )
    con = app.state.con.cursor()
    return insert_span(con, payload)


@app.post("/audit/{span_id}/replay")
def audit_replay(span_id: str):
    """Run replay for ONE captured span (fan-out to lower thinking levels)."""
    return run_replays(app.state.con.cursor(), span_id=span_id)


@app.post("/audit/{span_id}/judge")
def audit_judge(span_id: str):
    """Judge ONE captured span's replay_results against the original."""
    return run_judges(app.state.con.cursor(), span_id=span_id)


@app.post("/spans", response_model=Span)
def post_span(payload: SpanIngest):
    con = app.state.con.cursor()
    span = insert_span(con, payload)
    return span


@app.get("/spans", response_model=list[Span])
def list_spans(limit: int = Query(50, ge=1, le=500),
               since: Optional[datetime] = None):
    con = app.state.con.cursor()
    if since:
        rows = con.execute(
            f"SELECT {SPAN_COLS} FROM spans WHERE created_at >= ? "
            f"ORDER BY created_at DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {SPAN_COLS} FROM spans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_span(r) for r in rows]


@app.get("/spans/{span_id}/detail", response_model=SpanDetail)
def span_detail(span_id: str):
    con = app.state.con.cursor()
    row = con.execute(
        f"SELECT {SPAN_COLS} FROM spans WHERE id=?", (span_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="span not found")
    span = _row_to_span(row)

    replay_rows = con.execute(
        """SELECT id, span_id, target_thinking_level, response_redacted,
                  input_tokens, output_tokens, thinking_tokens, latency_ms,
                  estimated_cost_usd, created_at
           FROM replay_results WHERE span_id=? ORDER BY target_thinking_level""",
        (span_id,),
    ).fetchall()
    replays = [
        ReplayResult(
            id=r[0], span_id=r[1], target_thinking_level=r[2],
            response_redacted=r[3], input_tokens=r[4], output_tokens=r[5],
            thinking_tokens=r[6], latency_ms=r[7],
            estimated_cost_usd=r[8], created_at=r[9],
        ) for r in replay_rows
    ]

    judge_rows = con.execute(
        """SELECT id, span_id, replay_result_id, original_level,
                  alternative_level, verdict, confidence, reasoning,
                  votes_json, recommended_level, estimated_savings_usd,
                  created_at
           FROM judge_results WHERE span_id=? ORDER BY alternative_level""",
        (span_id,),
    ).fetchall()
    judges = [
        JudgeResult(
            id=r[0], span_id=r[1], replay_result_id=r[2],
            original_level=r[3], alternative_level=r[4], verdict=r[5],
            confidence=r[6], reasoning=r[7],
            votes=_votes_loads(r[8]), recommended_level=r[9],
            estimated_savings_usd=r[10], created_at=r[11],
        ) for r in judge_rows
    ]

    return SpanDetail(span=span, replays=replays, judges=judges)


# ---------------- waste report ----------------

_BEST_PER_SPAN_SQL = """
-- For each span pick the SINGLE best (= lowest level) replay that the
-- judge marked 'equivalent'. That is the recommended downgrade. Savings
-- count once per span; no triple-counting across replay levels.
WITH eq AS (
    SELECT
        j.span_id,
        j.alternative_level,
        j.estimated_savings_usd,
        j.original_level,
        s.task_label,
        s.estimated_cost_usd AS original_cost
    FROM judge_results j
    JOIN spans s ON s.id = j.span_id
    WHERE j.verdict = 'equivalent'
      AND j.estimated_savings_usd > 0
),
ranked AS (
    SELECT
        eq.*,
        CASE eq.alternative_level
            WHEN 'minimal' THEN 0
            WHEN 'low' THEN 1
            WHEN 'medium' THEN 2
            WHEN 'high' THEN 3
        END AS lvl_rank
    FROM eq
),
best AS (
    SELECT span_id, MIN(lvl_rank) AS best_rank FROM ranked GROUP BY 1
)
SELECT
    r.span_id, r.alternative_level, r.estimated_savings_usd,
    r.original_level, r.task_label, r.original_cost
FROM ranked r
JOIN best b ON b.span_id = r.span_id AND b.best_rank = r.lvl_rank
"""


def _observed_days(con) -> float:
    row = con.execute(
        "SELECT MIN(created_at), MAX(created_at) FROM spans"
    ).fetchone()
    if not row or not row[0]:
        return 1.0
    delta = (row[1] - row[0]).total_seconds() / 86400.0
    return max(delta, 1.0)  # avoid div-by-zero on single-day data


@app.get("/waste-report", response_model=WasteReport)
def waste_report():
    con = app.state.con.cursor()
    total_calls = con.execute("SELECT COUNT(*) FROM spans").fetchone()[0]

    best_rows = con.execute(_BEST_PER_SPAN_SQL).fetchall()
    waste_calls = len(best_rows)
    wasted_total = sum(r[2] for r in best_rows)

    days = _observed_days(con)
    monthly_projection = (wasted_total / days) * 30.0

    # Top patterns
    from collections import Counter, defaultdict
    pat_savings: dict[str, float] = defaultdict(float)
    pat_orig_lvl: dict[str, Counter] = defaultdict(Counter)
    pat_rec_lvl: dict[str, Counter] = defaultdict(Counter)
    pat_calls: Counter = Counter()
    for span_id, alt_level, savings, orig_level, task_label, orig_cost in best_rows:
        label = task_label or "(unlabeled)"
        pat_savings[label] += savings
        pat_calls[label] += 1
        pat_orig_lvl[label][orig_level] += 1
        pat_rec_lvl[label][alt_level] += 1
    top_patterns = sorted(pat_savings.items(), key=lambda x: -x[1])[:5]
    top_objs = [
        TopWastePattern(
            task_label=label,
            calls_with_waste=pat_calls[label],
            estimated_savings_usd=round(savings, 6),
            typical_original_level=pat_orig_lvl[label].most_common(1)[0][0],
            typical_recommended_level=pat_rec_lvl[label].most_common(1)[0][0],
        )
        for label, savings in top_patterns
    ]

    # Recommended downgrades
    pair_calls: Counter = Counter()
    pair_savings: dict[tuple[str, str], float] = defaultdict(float)
    for _, alt_level, savings, orig_level, *_ in best_rows:
        pair_calls[(orig_level, alt_level)] += 1
        pair_savings[(orig_level, alt_level)] += savings
    downgrades = sorted(
        pair_savings.items(), key=lambda x: -x[1]
    )[:5]
    downgrade_objs = [
        RecommendedDowngrade(
            from_level=k[0],
            to_level=k[1],
            affected_calls=pair_calls[k],
            estimated_savings_usd=round(v, 6),
        )
        for k, v in downgrades
    ]

    return WasteReport(
        total_calls_audited=total_calls,
        calls_with_likely_waste=waste_calls,
        estimated_cost_wasted_usd=round(wasted_total, 6),
        monthly_projection_usd=round(monthly_projection, 6),
        observed_days=round(days, 3),
        top_wasteful_patterns=top_objs,
        recommended_downgrades=downgrade_objs,
        demo_mode=_demo_mode(),
    )


# ---------------- waste map ----------------

_WASTE_MAP_SQL = """
-- Group spans by (task_label, prompt_hash, original_level). For each
-- group, pick the dominant verdict across all judge_results that involve
-- those spans. Color:
--   equivalent             -> red    (waste — go lower)
--   materially_different   -> red    (risk — original was wrong OR replay was wrong)
--   degraded               -> green  (HIGH justified, lower replays worse)
--   uncertain              -> yellow
-- Plus surface the recommended_level for the cell.
WITH per_span_best AS (""" + _BEST_PER_SPAN_SQL + """
)
SELECT
    s.task_label,
    s.prompt_hash,
    s.thinking_level_used AS original_level,
    COUNT(DISTINCT s.id) AS span_count,
    -- equivalent_sample_count = how many of those spans had a best equivalent
    -- replay at any level (= "this many were safely downgradeable").
    COUNT(DISTINCT psb.span_id) AS equivalent_sample_count,
    MAX(CASE WHEN psb.span_id IS NOT NULL THEN 1 ELSE 0 END) AS has_equivalent,
    -- group_savings counts each span's best replay once (psb is 0-or-1 row per span)
    COALESCE((
        SELECT SUM(psb2.estimated_savings_usd)
        FROM per_span_best psb2
        JOIN spans s2 ON s2.id = psb2.span_id
        WHERE s2.task_label IS NOT DISTINCT FROM s.task_label
          AND s2.prompt_hash = s.prompt_hash
          AND s2.thinking_level_used = s.thinking_level_used
    ), 0.0) AS group_savings,
    ANY_VALUE(psb.alternative_level) AS recommended_level,
    MAX(CASE WHEN j.verdict='materially_different' THEN 1 ELSE 0 END) AS has_risk,
    MAX(CASE WHEN j.verdict='uncertain' THEN 1 ELSE 0 END) AS has_uncertain
FROM spans s
LEFT JOIN per_span_best psb ON psb.span_id = s.id
LEFT JOIN judge_results j ON j.span_id = s.id
GROUP BY s.task_label, s.prompt_hash, s.thinking_level_used
ORDER BY group_savings DESC, span_count DESC
"""


@app.get("/policy")
def export_policy(format: str = Query("json", regex="^(json|python|yaml)$")):
    """Recommended thinking_level per task_label, derived from the audit.

    For each task_label, picks the most common (lowest equivalent) recommended
    level across spans where the judge marked a downgrade safe. Patterns with
    no safe downgrade get the level the audit observed them at (= keep as-is).

    Output formats:
      json   — {"task_label": "minimal", ...} machine-readable
      python — a copy-pasteable THINKING_POLICY dict
      yaml   — a flat key:value YAML file
    """
    from collections import Counter, defaultdict
    con = app.state.con.cursor()

    # Best-per-span: lowest-level equivalent downgrade for each span.
    best_rows = con.execute(_BEST_PER_SPAN_SQL).fetchall()

    # task_label -> Counter of recommended alt_level
    rec_per_label: dict[str, Counter] = defaultdict(Counter)
    for _span_id, alt_level, _savings, _orig_level, task_label, _cost in best_rows:
        rec_per_label[task_label or "(unlabeled)"][alt_level] += 1

    # For patterns where no downgrade was found, fall back to the level the
    # audit observed them at (= keep as-is).
    keep_rows = con.execute(
        """SELECT s.task_label, s.thinking_level_used, COUNT(*)
           FROM spans s
           WHERE s.id NOT IN (SELECT span_id FROM (""" + _BEST_PER_SPAN_SQL + """))
           GROUP BY s.task_label, s.thinking_level_used"""
    ).fetchall()
    keep_per_label: dict[str, Counter] = defaultdict(Counter)
    for label, level, n in keep_rows:
        keep_per_label[label or "(unlabeled)"][level] += n

    policy: dict[str, str] = {}
    all_labels = set(rec_per_label) | set(keep_per_label)
    for label in sorted(all_labels):
        if rec_per_label.get(label):
            # downgrade exists — use most common
            policy[label] = rec_per_label[label].most_common(1)[0][0]
        else:
            # keep as-is — use most common observed level
            policy[label] = keep_per_label[label].most_common(1)[0][0]

    if format == "json":
        return policy
    if format == "python":
        lines = ["# Thinklet recommended thinking-budget policy",
                 "# Generated from waste-map audit results.",
                 "THINKING_POLICY = {"]
        for k, v in policy.items():
            lines.append(f"    {k!r}: {v!r},")
        lines.append("}")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/x-python")
    # yaml
    lines = ["# Thinklet recommended thinking-budget policy"]
    for k, v in policy.items():
        # quote keys that contain special chars
        key = k if all(c.isalnum() or c in "_-" for c in k) else repr(k)
        lines.append(f"{key}: {v}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/yaml")


@app.get("/cell-history", response_model=CellHistory)
def cell_history(
    task_label: str = Query(...),
    prompt_hash: str = Query(...),
    original_level: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
):
    """All spans matching one Waste Map cell, with each span's best verdict.

    Distinguishes robust patterns (every sample = equivalent) from flappy
    ones (some equivalent, some uncertain) at a glance.
    """
    con = app.state.con.cursor()
    label_match = "s.task_label IS NULL" if task_label == "(unlabeled)" else "s.task_label = ?"
    params: tuple = (prompt_hash, original_level)
    if task_label != "(unlabeled)":
        params = (task_label,) + params

    sql = f"""
        SELECT s.id, s.created_at, s.thinking_tokens, s.estimated_cost_usd
        FROM spans s
        WHERE {label_match}
          AND s.prompt_hash = ?
          AND s.thinking_level_used = ?
        ORDER BY s.created_at DESC
        LIMIT {int(limit)}
    """
    span_rows = con.execute(sql, params).fetchall()

    samples: list[CellSampleSummary] = []
    rank = {"minimal": 0, "low": 1, "medium": 2, "high": 3}
    for sid, created, thinking, cost in span_rows:
        # Per-span best verdict: lowest-level equivalent w/ positive savings,
        # else the highest-confidence non-uncertain, else the first.
        jrows = con.execute(
            """SELECT alternative_level, verdict, confidence, estimated_savings_usd
               FROM judge_results WHERE span_id = ?""",
            (sid,),
        ).fetchall()
        best_v = best_lvl = None
        best_save = 0.0
        equiv = [r for r in jrows if r[1] == "equivalent" and r[3] > 0]
        if equiv:
            equiv.sort(key=lambda r: rank[r[0]])
            best_lvl, best_v, _conf, best_save = equiv[0]
        elif jrows:
            jrows.sort(key=lambda r: -r[2])
            best_lvl, best_v, _conf, best_save = jrows[0]
        samples.append(
            CellSampleSummary(
                span_id=sid,
                created_at=created,
                thinking_tokens=thinking,
                estimated_cost_usd=cost,
                best_verdict=best_v,
                best_alternative_level=best_lvl,
                best_savings_usd=round(best_save or 0.0, 8),
            )
        )

    return CellHistory(
        task_label=task_label,
        prompt_hash=prompt_hash,
        original_level=original_level,  # type: ignore[arg-type]
        sample_count=len(samples),
        samples=samples,
    )


@app.get("/waste-map", response_model=list[WasteMapCell])
def waste_map():
    con = app.state.con.cursor()
    rows = con.execute(_WASTE_MAP_SQL).fetchall()
    cells: list[WasteMapCell] = []
    for r in rows:
        (task_label, prompt_hash, original_level, span_count,
         equivalent_sample_count,
         has_equivalent, group_savings, recommended_level,
         has_risk, has_uncertain) = r
        if has_equivalent:
            verdict = "equivalent"
            color = "red"
        elif has_risk and original_level == "minimal":
            # Original too low → risk to quality
            verdict = "materially_different"
            color = "red"
        elif has_uncertain:
            verdict = "uncertain"
            color = "yellow"
        else:
            verdict = "degraded"
            color = "green"
        # Confidence = fraction of audited samples that had a safe downgrade.
        # Only meaningful for "equivalent" cells; reported as 0..1.
        eq_rate = (equivalent_sample_count / span_count) if span_count else 0.0
        cells.append(
            WasteMapCell(
                task_label=task_label or "(unlabeled)",
                prompt_hash=prompt_hash,
                original_level=original_level,
                recommended_level=recommended_level,
                verdict=verdict,
                color=color,
                span_count=span_count,
                estimated_savings_usd=round(group_savings or 0.0, 6),
                equivalent_sample_count=int(equivalent_sample_count or 0),
                equivalent_rate=round(eq_rate, 3),
            )
        )
    return cells
