"""Demo seed generator for Thinklet.

Produces a deterministic dataset of ~120 spans across planted waste patterns,
plus matching replay_results and judge_results so the dashboard has a complete
end-to-end story without needing the replay/judge engines (Phases 4-5).

Patterns (all visible on the dashboard):
  greeting        - HIGH used, MINIMAL equivalent (waste)
  classification  - HIGH used, MINIMAL equivalent (waste)
  extraction      - MEDIUM used, LOW equivalent (waste)
  summarization   - HIGH used, LOW equivalent (partial waste)
  coding_debug    - HIGH used, HIGH justified (no waste)
  hard_reasoning  - HIGH used, HIGH justified (no waste)
  risky_math      - MINIMAL used, quality degraded (RISK, not waste)
"""
from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import connect
from .pricing import estimate_cost

LEVELS = ["minimal", "low", "medium", "high"]
LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

DEMO_MODEL = "gemini-3.5-flash"

# Latency multipliers per level.
_LEVEL_LATENCY_MULT = {"minimal": 1.0, "low": 1.5, "medium": 2.4, "high": 4.2}

# Thinking-token burn per level. In demo we model thinking_tokens as a
# SEPARATE field (matching Gemini's `thoughts_token_count` in usage_metadata),
# distinct from `candidates_token_count` (output_tokens). This is the heart of
# the Thinklet story: hidden thinking burn that the user doesn't see in the
# response but pays for.
_LEVEL_THINKING_TOKENS = {"minimal": 0, "low": 180, "medium": 720, "high": 2800}
# Per-pattern noise lets the dashboard look realistic (not all spans identical).
_THINKING_NOISE_PCT = 0.25


@dataclass(frozen=True)
class Pattern:
    label: str
    count: int
    original_level: str
    recommended_level: str  # the level the judge will recommend
    verdict_for_recommended: str  # 'equivalent' | 'degraded' | 'materially_different' | 'uncertain'
    prompt_template: str
    response_template: str  # the original-level response
    base_input_tokens: int
    base_output_tokens: int  # response tokens only — visible to user
    base_latency_ms: int  # at MINIMAL; scaled up by level multiplier


PATTERNS: list[Pattern] = [
    Pattern(
        label="greeting",
        count=20,
        original_level="high",
        recommended_level="minimal",
        verdict_for_recommended="equivalent",
        prompt_template="Reply with a one-sentence greeting for customer #{i}.",
        response_template="Hi! Thanks for reaching out — happy to help today.",
        base_input_tokens=18,
        base_output_tokens=20,
        base_latency_ms=320,
    ),
    Pattern(
        label="classification",
        count=22,
        original_level="high",
        recommended_level="minimal",
        verdict_for_recommended="equivalent",
        prompt_template=(
            "Classify the sentiment of this review as positive/negative/neutral.\n"
            "Review #{i}: 'The product works as advertised, no complaints.'"
        ),
        response_template="positive",
        base_input_tokens=42,
        base_output_tokens=4,
        base_latency_ms=280,
    ),
    Pattern(
        label="extraction",
        count=20,
        original_level="medium",
        recommended_level="low",
        verdict_for_recommended="equivalent",
        prompt_template=(
            "Extract the order id from this email and return JSON {{\"order_id\": ...}}.\n"
            "Email #{i}: 'Your order ORD-{i:05d} has shipped.'"
        ),
        response_template='{"order_id": "ORD-00042"}',
        base_input_tokens=55,
        base_output_tokens=18,
        base_latency_ms=390,
    ),
    Pattern(
        label="summarization",
        count=18,
        original_level="high",
        recommended_level="low",
        verdict_for_recommended="equivalent",
        prompt_template=(
            "Summarize the meeting notes #{i} in 2 sentences.\n"
            "Notes: 'Team reviewed Q3 launch checklist. Engineering will own QA.'"
        ),
        response_template=(
            "The team reviewed the Q3 launch checklist. Engineering will own QA."
        ),
        base_input_tokens=60,
        base_output_tokens=32,
        base_latency_ms=520,
    ),
    Pattern(
        label="coding_debug",
        count=15,
        original_level="high",
        recommended_level="high",
        verdict_for_recommended="degraded",
        prompt_template=(
            "Debug this Python stack trace #{i}, explain root cause, propose patch.\n"
            "Trace: 'TypeError: unsupported operand type(s) for +: NoneType and int'"
        ),
        response_template=(
            "Root cause: a function returned None where an int was expected. "
            "Patch: add a default return or guard the caller with `value or 0` "
            "before the addition. Add a unit test covering the None branch."
        ),
        base_input_tokens=85,
        base_output_tokens=140,
        base_latency_ms=900,
    ),
    Pattern(
        label="hard_reasoning",
        count=10,
        original_level="high",
        recommended_level="high",
        verdict_for_recommended="materially_different",
        prompt_template=(
            "Solve step-by-step #{i}: A train leaves at 9:15 going 80mph, another "
            "at 9:50 going 100mph in pursuit. When do they meet?"
        ),
        response_template=(
            "The lead train has a 35-minute (7/12 hr) head start, covering "
            "80 * 7/12 ≈ 46.67 miles. The pursuer closes at 20 mph, taking "
            "46.67/20 ≈ 2.33 hours after 9:50 — so they meet at ~12:10."
        ),
        base_input_tokens=95,
        base_output_tokens=180,
        base_latency_ms=1100,
    ),
    Pattern(
        label="risky_math",
        count=10,
        original_level="minimal",
        recommended_level="high",
        verdict_for_recommended="materially_different",
        prompt_template=(
            "What is the integral of x^2 * sin(x) from 0 to pi? #{i}"
        ),
        response_template="About 5.87.",  # the MINIMAL answer is wrong/imprecise
        base_input_tokens=22,
        base_output_tokens=12,
        base_latency_ms=180,
    ),
    Pattern(
        label="uncertain_general",
        count=5,
        original_level="medium",
        recommended_level="low",
        verdict_for_recommended="uncertain",
        prompt_template=(
            "Recommend a tagline for a coffee shop targeting remote workers. #{i}"
        ),
        response_template="Brew. Focus. Repeat.",
        base_input_tokens=24,
        base_output_tokens=14,
        base_latency_ms=410,
    ),
]


def _hash(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return h[:32]


def _det_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(parts)))


def _scaled_latency(base: int, level: str) -> int:
    return max(50, int(base * _LEVEL_LATENCY_MULT[level]))


def _thinking_tokens_for(level: str, rng: random.Random) -> int:
    base = _LEVEL_THINKING_TOKENS[level]
    if base == 0:
        return 0
    jitter = 1.0 + rng.uniform(-_THINKING_NOISE_PCT, _THINKING_NOISE_PCT)
    return max(1, int(base * jitter))


def _replay_response(original: str, target_level: str) -> str:
    """Deterministic-looking replay output. For 'equivalent'-pattern replays
    we return the same response (to make verdict='equivalent' believable).
    For 'degraded' levels we shorten/strip detail."""
    if target_level in ("minimal", "low"):
        # Slight rewording so it isn't an exact-string match (judge LLM path).
        return original.replace("The team", "Team").replace("Hi! ", "Hi — ")
    return original


def _make_replay_for(
    pattern: Pattern,
    span_id: str,
    prompt: str,
    original_response: str,
    target_level: str,
    created_at: datetime,
    rng: random.Random,
) -> dict:
    thinking = _thinking_tokens_for(target_level, rng)
    latency = _scaled_latency(pattern.base_latency_ms, target_level)
    response = _replay_response(original_response, target_level)
    cost = estimate_cost(
        DEMO_MODEL,
        pattern.base_input_tokens,
        pattern.base_output_tokens,
        thinking,
    )
    return {
        "id": _det_id("replay", span_id, target_level),
        "span_id": span_id,
        "target_thinking_level": target_level,
        "response_redacted": response,
        "input_tokens": pattern.base_input_tokens,
        "output_tokens": pattern.base_output_tokens,
        "thinking_tokens": thinking,
        "latency_ms": latency,
        "estimated_cost_usd": cost,
        "created_at": created_at,
    }


def _verdict_for_replay(pattern: Pattern, target_level: str) -> tuple[str, float]:
    """Return (verdict, confidence) for a replay at `target_level`.

    The plan: at the recommended level, use the pattern's verdict_for_recommended.
    For levels between original and recommended, also call it equivalent if
    the pattern is a waste pattern. For levels strictly below recommended on
    waste patterns, mark degraded (we're going too low). For risky_math
    (MINIMAL original), recommended is HIGHER, so logic reverses.
    """
    orig_rank = LEVEL_RANK[pattern.original_level]
    rec_rank = LEVEL_RANK[pattern.recommended_level]
    tgt_rank = LEVEL_RANK[target_level]

    if pattern.verdict_for_recommended == "uncertain":
        if tgt_rank == rec_rank:
            return "uncertain", 0.42
        return ("equivalent", 0.6) if tgt_rank > rec_rank else ("degraded", 0.7)

    if rec_rank < orig_rank:
        # Standard waste pattern: lower levels (between orig and rec) are safe.
        if tgt_rank >= rec_rank:
            return pattern.verdict_for_recommended, 0.88
        return "degraded", 0.78

    if rec_rank > orig_rank:
        # Risky pattern: original was too low. Lower levels are worse,
        # higher levels are recommended.
        if tgt_rank > orig_rank:
            # If we replayed at the higher recommended level it would be
            # better — verdict says original is materially_different from
            # the better alternative.
            return pattern.verdict_for_recommended, 0.83
        return "equivalent", 0.5  # below-or-equal still bad

    # rec_rank == orig_rank: HIGH is justified, lower replays are worse.
    if tgt_rank < orig_rank:
        return pattern.verdict_for_recommended, 0.85
    return "equivalent", 0.5


def _make_judge_for(
    pattern: Pattern,
    span_id: str,
    replay_row: dict,
    original_cost: float,
    created_at: datetime,
) -> dict:
    verdict, conf = _verdict_for_replay(pattern, replay_row["target_thinking_level"])
    recommended_level: Optional[str] = (
        pattern.recommended_level if verdict in ("equivalent", "materially_different") else None
    )
    if verdict == "uncertain":
        recommended_level = None

    # Savings only count if lower-level replay is equivalent.
    savings = 0.0
    if verdict == "equivalent" and (
        LEVEL_RANK[replay_row["target_thinking_level"]]
        < LEVEL_RANK[pattern.original_level]
    ):
        savings = max(0.0, original_cost - replay_row["estimated_cost_usd"])

    votes = [verdict, verdict, verdict] if conf >= 0.7 else [verdict, "uncertain", verdict]

    return {
        "id": _det_id("judge", span_id, replay_row["target_thinking_level"]),
        "span_id": span_id,
        "replay_result_id": replay_row["id"],
        "original_level": pattern.original_level,
        "alternative_level": replay_row["target_thinking_level"],
        "verdict": verdict,
        "confidence": conf,
        "reasoning": _reasoning(pattern, replay_row["target_thinking_level"], verdict),
        "votes_json": json.dumps(votes),
        "recommended_level": recommended_level,
        "estimated_savings_usd": round(savings, 8),
        "created_at": created_at,
    }


def _reasoning(pattern: Pattern, target: str, verdict: str) -> str:
    if verdict == "equivalent":
        return (
            f"Replay at {target} satisfies the {pattern.label} task as well as "
            f"the {pattern.original_level} original. No loss of correctness or "
            f"format compliance."
        )
    if verdict == "degraded":
        return (
            f"Replay at {target} produces a shorter / less complete answer "
            f"than the {pattern.original_level} original for a {pattern.label} task."
        )
    if verdict == "materially_different":
        return (
            f"Replay at {target} disagrees on substance with the original for "
            f"this {pattern.label} task — switching levels would change the "
            f"answer the user sees."
        )
    return f"Judge votes split between equivalent and uncertain for {pattern.label}."


def _lower_levels(level: str) -> list[str]:
    rank = LEVEL_RANK[level]
    return [lvl for lvl, r in LEVEL_RANK.items() if r < rank]


def _higher_levels(level: str) -> list[str]:
    rank = LEVEL_RANK[level]
    return [lvl for lvl, r in LEVEL_RANK.items() if r > rank]


def _replay_targets(pattern: Pattern) -> list[str]:
    """Replay at all OTHER levels for richer dashboard data.

    For risky_math (MINIMAL original) we replay at higher levels too — the
    judge then reveals that the original was too cheap. For waste patterns
    we only replay at lower levels per the prompt spec.
    """
    if pattern.original_level == "minimal":
        return _higher_levels(pattern.original_level)
    return _lower_levels(pattern.original_level)


def generate_demo_data(con) -> dict:
    """Build and insert all demo rows. Returns counts for reporting."""
    rng = random.Random(42)
    now = datetime.now(timezone.utc)

    spans: list[tuple] = []
    replays: list[tuple] = []
    judges: list[tuple] = []
    replay_jobs: list[tuple] = []

    for pattern in PATTERNS:
        for i in range(pattern.count):
            # Spread created_at across the last 3 days for monthly projection.
            offset_minutes = rng.randint(0, 3 * 24 * 60)
            created_at = now - timedelta(minutes=offset_minutes)

            prompt = pattern.prompt_template.format(i=i)
            response = pattern.response_template
            prompt_hash = _hash(DEMO_MODEL, pattern.label, "v1")  # same per pattern -> grouping works

            thinking_tokens = _thinking_tokens_for(pattern.original_level, rng)
            latency = _scaled_latency(pattern.base_latency_ms, pattern.original_level)
            cost = estimate_cost(
                DEMO_MODEL,
                pattern.base_input_tokens,
                pattern.base_output_tokens,
                thinking_tokens,
            )

            span_id = _det_id("span", pattern.label, str(i))
            spans.append((
                span_id,
                created_at,
                _det_id("trace", pattern.label, str(i)),
                _det_id("call", pattern.label, str(i)),
                prompt_hash,
                prompt,
                response,
                DEMO_MODEL,
                pattern.original_level,
                pattern.base_input_tokens,
                pattern.base_output_tokens,
                thinking_tokens,
                pattern.base_input_tokens + pattern.base_output_tokens + thinking_tokens,
                latency,
                cost,
                pattern.label,
                "demo",
            ))

            for target_level in _replay_targets(pattern):
                replay_row = _make_replay_for(
                    pattern, span_id, prompt, response, target_level, created_at, rng
                )
                replays.append((
                    replay_row["id"],
                    replay_row["span_id"],
                    replay_row["target_thinking_level"],
                    replay_row["response_redacted"],
                    replay_row["input_tokens"],
                    replay_row["output_tokens"],
                    replay_row["thinking_tokens"],
                    replay_row["latency_ms"],
                    replay_row["estimated_cost_usd"],
                    replay_row["created_at"],
                ))

                judge_row = _make_judge_for(pattern, span_id, replay_row, cost, created_at)
                judges.append((
                    judge_row["id"],
                    judge_row["span_id"],
                    judge_row["replay_result_id"],
                    judge_row["original_level"],
                    judge_row["alternative_level"],
                    judge_row["verdict"],
                    judge_row["confidence"],
                    judge_row["reasoning"],
                    judge_row["votes_json"],
                    judge_row["recommended_level"],
                    judge_row["estimated_savings_usd"],
                    judge_row["created_at"],
                ))

                replay_jobs.append((
                    _det_id("job", span_id, target_level),
                    span_id,
                    prompt_hash,
                    target_level,
                    "completed",
                    1,
                    None,
                    created_at,
                    created_at,
                ))

    # Wipe & insert. Seed is deterministic and idempotent over (pattern, i, level).
    con.execute("DELETE FROM judge_results")
    con.execute("DELETE FROM replay_results")
    con.execute("DELETE FROM replay_jobs")
    con.execute("DELETE FROM spans")

    con.executemany(
        """
        INSERT INTO spans (id, created_at, trace_id, call_id, prompt_hash,
            prompt_redacted, response_redacted, model, thinking_level_used,
            input_tokens, output_tokens, thinking_tokens, total_tokens,
            latency_ms, estimated_cost_usd, task_label, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        spans,
    )
    con.executemany(
        """
        INSERT INTO replay_results (id, span_id, target_thinking_level,
            response_redacted, input_tokens, output_tokens, thinking_tokens,
            latency_ms, estimated_cost_usd, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        replays,
    )
    con.executemany(
        """
        INSERT INTO judge_results (id, span_id, replay_result_id,
            original_level, alternative_level, verdict, confidence, reasoning,
            votes_json, recommended_level, estimated_savings_usd, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        judges,
    )
    con.executemany(
        """
        INSERT INTO replay_jobs (id, span_id, prompt_hash,
            target_thinking_level, status, attempts, error,
            created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        replay_jobs,
    )

    return {
        "spans": len(spans),
        "replays": len(replays),
        "judges": len(judges),
        "replay_jobs": len(replay_jobs),
    }


if __name__ == "__main__":
    con = connect()
    counts = generate_demo_data(con)
    print(f"[seed] inserted {counts}")
