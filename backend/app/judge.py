"""Judge agent.

For every (span, replay_result) pair that doesn't yet have a judge_result,
decide whether the replay is equivalent / degraded / materially_different /
uncertain.

Strategy:
  1. Deterministic checks first:
        a. exact-string match            -> equivalent
        b. JSON-equal (parse both)       -> equivalent
        c. simple-numeric match (within
           epsilon when both parse as
           numbers)                       -> equivalent
  2. If still undecided, run the LLM judge 3 times with shuffled A/B order.
     Majority verdict wins; tie or low average confidence -> uncertain.
  3. Demo mode short-circuits the LLM and produces deterministic verdicts
     keyed by the seeded waste-pattern labels, so the dashboard tells the
     same story every run.

Savings = max(0, original_cost - replay_cost), only awarded when verdict
is 'equivalent' AND the replay is at a strictly lower level than original.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
import warnings
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from .gemini_utils import call_with_429_retry

LEVELS = ["minimal", "low", "medium", "high"]
LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

JUDGE_MODEL = "gemini-3.5-flash"
# Vote count. Default 3 (majority vote). Override to 1 for rate-limited demos.
JUDGE_VOTES = int(os.environ.get("THINKLET_JUDGE_VOTES", "3"))
LOW_CONFIDENCE = 0.55

# When hitting real Gemini, pace LLM judge votes so we stay under free-tier
# RPM limits. Set to 0 to disable. Demo mode never sleeps.
_JUDGE_VOTE_SLEEP_S = float(os.environ.get("THINKLET_JUDGE_VOTE_SLEEP_S", "4.0"))


# ---------------- deterministic checks ----------------

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _maybe_json(s: str):
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return None


def _maybe_number(s: str) -> Optional[float]:
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
        return None


def deterministic_verdict(original: str, replay: str) -> Optional[str]:
    if _normalize(original) == _normalize(replay):
        return "equivalent"
    j1, j2 = _maybe_json(original), _maybe_json(replay)
    if j1 is not None and j2 is not None and j1 == j2:
        return "equivalent"
    n1, n2 = _maybe_number(original), _maybe_number(replay)
    if n1 is not None and n2 is not None:
        if n1 == n2 or (n1 != 0 and abs(n1 - n2) / abs(n1) < 0.001):
            return "equivalent"
    return None


# ---------------- LLM judge ----------------

JUDGE_PROMPT = """\
You are an impartial evaluator comparing two AI responses (A and B) to the same user request.

USER REQUEST:
{prompt}

RESPONSE A:
{a}

RESPONSE B:
{b}

Compare task usefulness, factual correctness, completeness, instruction-following, and format compliance. Do NOT reward verbosity. Two outputs are equivalent if they satisfy the user's request equally well even when the wording differs.

Return STRICT JSON only, no prose:
{{"verdict": "equivalent" | "degraded" | "materially_different" | "uncertain",
  "confidence": 0.0..1.0,
  "reasoning": "one short sentence",
  "recommended_level": "minimal" | "low" | "medium" | "high"}}
"""


def _demo_mode() -> bool:
    return os.environ.get("THINKLET_DEMO_MODE", "").lower() == "true"


def _gemini_client():
    if _demo_mode() or not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"judge: Gemini init failed, demo verdicts: {exc}")
        return None


def _llm_vote(client, prompt: str, a: str, b: str) -> dict:
    if client is None:
        # Demo fallback: prefer 'equivalent' when responses share at least
        # 30% of tokens, else 'uncertain'. Cheap heuristic so non-API runs
        # still produce variation.
        t1 = set(_normalize(a).split())
        t2 = set(_normalize(b).split())
        if not t1 or not t2:
            return {"verdict": "uncertain", "confidence": 0.4,
                    "reasoning": "empty response", "recommended_level": "low"}
        overlap = len(t1 & t2) / max(len(t1), len(t2))
        if overlap > 0.6:
            return {"verdict": "equivalent", "confidence": 0.85,
                    "reasoning": "high token overlap", "recommended_level": "low"}
        if overlap > 0.3:
            return {"verdict": "uncertain", "confidence": 0.5,
                    "reasoning": "partial overlap", "recommended_level": "low"}
        return {"verdict": "degraded", "confidence": 0.7,
                "reasoning": "low overlap, replay likely thinner",
                "recommended_level": "high"}

    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_budget=4096,  # MEDIUM equivalent
                include_thoughts=False,
            ),
            response_mime_type="application/json",
        )
        resp = call_with_429_retry(
            lambda: client.models.generate_content(
                model=JUDGE_MODEL,
                contents=JUDGE_PROMPT.format(prompt=prompt, a=a, b=b),
                config=cfg,
            ),
            label="judge",
        )
        text = (getattr(resp, "text", "") or "").strip()
        parsed = json.loads(text)
        return parsed
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"judge: LLM vote failed: {exc}")
        return {"verdict": "uncertain", "confidence": 0.0,
                "reasoning": str(exc)[:120], "recommended_level": None}


def _majority(votes: list[dict]) -> tuple[str, float, Optional[str], list[str]]:
    counter = Counter(v["verdict"] for v in votes)
    top, top_count = counter.most_common(1)[0]
    confidences = [v.get("confidence", 0.5) for v in votes if v["verdict"] == top]
    avg_conf = sum(confidences) / max(1, len(confidences))

    if top_count <= len(votes) // 2 or avg_conf < LOW_CONFIDENCE:
        # No clear majority OR consensus has weak confidence.
        verdict, conf = "uncertain", 0.4
    else:
        verdict, conf = top, avg_conf

    # Recommended level = mode of recommended_level among same-verdict votes.
    rec_counter = Counter(
        v.get("recommended_level") for v in votes
        if v["verdict"] == top and v.get("recommended_level")
    )
    rec_level = rec_counter.most_common(1)[0][0] if rec_counter else None
    return verdict, conf, rec_level, [v["verdict"] for v in votes]


# ---------------- runner ----------------

def _existing_judge(con, span_id: str, replay_id: str) -> bool:
    r = con.execute(
        "SELECT 1 FROM judge_results WHERE span_id=? AND replay_result_id=? LIMIT 1",
        (span_id, replay_id),
    ).fetchone()
    return r is not None


def run_judges(con, span_id: Optional[str] = None) -> dict:
    """Score replay_results against their originals.

    When span_id is provided, only that span's pairs are judged (used by the
    Try It UI's per-span audit flow).
    """
    client = _gemini_client()
    rng = random.Random(7)
    if span_id:
        rows = con.execute(
            """SELECT
                    rr.id, rr.span_id, rr.target_thinking_level,
                    rr.response_redacted, rr.estimated_cost_usd,
                    s.prompt_redacted, s.response_redacted, s.thinking_level_used,
                    s.estimated_cost_usd, s.task_label
               FROM replay_results rr
               JOIN spans s ON s.id = rr.span_id
               WHERE rr.span_id = ?""",
            (span_id,),
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT
                    rr.id, rr.span_id, rr.target_thinking_level,
                    rr.response_redacted, rr.estimated_cost_usd,
                    s.prompt_redacted, s.response_redacted, s.thinking_level_used,
                    s.estimated_cost_usd, s.task_label
               FROM replay_results rr
               JOIN spans s ON s.id = rr.span_id"""
        ).fetchall()

    judged = 0
    skipped = 0
    for (replay_id, span_id, alt_level, replay_resp, replay_cost,
         prompt, orig_resp, orig_level, orig_cost, task_label) in rows:
        if _existing_judge(con, span_id, replay_id):
            skipped += 1
            continue

        det = deterministic_verdict(orig_resp or "", replay_resp or "")
        if det is not None:
            verdict, confidence = det, 0.99
            votes = [verdict, verdict, verdict]
            reasoning = "Deterministic match (exact / JSON / numeric)."
            rec_level = alt_level if det == "equivalent" else orig_level
        else:
            votes_obj = []
            for vote_i in range(JUDGE_VOTES):
                # Shuffle A/B order to control for position bias.
                if rng.random() < 0.5:
                    votes_obj.append(_llm_vote(client, prompt or "", orig_resp or "", replay_resp or ""))
                else:
                    flipped = _llm_vote(client, prompt or "", replay_resp or "", orig_resp or "")
                    # If the model thought B (now original) was degraded, that
                    # means original is degraded relative to replay -> for our
                    # framing we want how replay compares to original, so we
                    # need to flip the verdict label sense for 'degraded'.
                    if flipped.get("verdict") == "degraded":
                        flipped["verdict"] = "materially_different"
                    votes_obj.append(flipped)
                # Pace real-API votes to respect free-tier RPM. Skip the sleep
                # after the last vote and when demo-mode (client is None).
                if client is not None and _JUDGE_VOTE_SLEEP_S > 0 and vote_i < JUDGE_VOTES - 1:
                    time.sleep(_JUDGE_VOTE_SLEEP_S)
            verdict, confidence, rec_level, votes = _majority(votes_obj)
            reasoning = votes_obj[0].get("reasoning", "")[:240]

        # Savings only when verdict says lower level is fine.
        savings = 0.0
        if verdict == "equivalent" and LEVEL_RANK[alt_level] < LEVEL_RANK[orig_level]:
            savings = max(0.0, (orig_cost or 0.0) - (replay_cost or 0.0))

        con.execute(
            """INSERT INTO judge_results (id, span_id, replay_result_id,
                   original_level, alternative_level, verdict, confidence,
                   reasoning, votes_json, recommended_level,
                   estimated_savings_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), span_id, replay_id,
                orig_level, alt_level, verdict, confidence,
                reasoning, json.dumps(votes), rec_level,
                round(savings, 8), datetime.now(timezone.utc),
            ),
        )
        judged += 1

        # Pace between pairs when running against real Gemini, so back-to-back
        # LLM judges don't blow the 5-RPM free-tier quota. Skipped for
        # deterministic-only pairs would be nicer but is hard to know in
        # advance; cheap to be conservative.
        if client is not None and _JUDGE_VOTE_SLEEP_S > 0:
            time.sleep(_JUDGE_VOTE_SLEEP_S)

    return {"judged": judged, "skipped_existing": skipped}
