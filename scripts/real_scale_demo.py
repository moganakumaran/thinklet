"""Scale-up real-Gemini demo: 5 varied prompts across the planted-pattern taxonomy.

The 5 prompts are deliberately picked so the Waste Map tells a complete story
when run against a real Gemini API key:

  1. greeting_real        HIGH  -> expect equivalent at MINIMAL (waste)
  2. sentiment_real       HIGH  -> expect equivalent at MINIMAL (waste)
  3. extraction_real      MEDIUM-> expect equivalent at LOW       (waste)
  4. summarization_real   HIGH  -> expect equivalent at LOW       (waste)
  5. math_reasoning_real  HIGH  -> expect DEGRADED at lower       (HIGH justified)

After the originals are captured, the script triggers /replay/run and
/judge/run. Free-tier rate limits are respected by THINKLET_JUDGE_VOTE_SLEEP_S
inside the backend. Expect ~3-5 minutes wall-clock for the full audit.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "sdk"))

from thinklet_sdk import ThinkletClient  # noqa: E402

BACKEND = "http://localhost:8000"

SCENARIOS = [
    dict(
        task_label="greeting_real",
        thinking_level="high",
        prompt=(
            "Reply with one friendly sentence welcoming a returning customer "
            "named Alice."
        ),
    ),
    dict(
        task_label="sentiment_real",
        thinking_level="high",
        prompt=(
            "What's the sentiment of this review? Reply with one word: "
            "positive, negative, or neutral.\n"
            "Review: 'The shipping was fast and the product works as expected.'"
        ),
    ),
    dict(
        task_label="extraction_real",
        thinking_level="medium",
        prompt=(
            "Extract JSON with fields {\"order_id\": str, \"item_count\": int} "
            "from the following sentence. Return ONLY the JSON object.\n"
            "Sentence: 'Order ORD-8821 includes 3 items.'"
        ),
    ),
    dict(
        task_label="summarization_real",
        thinking_level="high",
        prompt=(
            "Summarize the following meeting notes in exactly one sentence:\n"
            "'The team met to review the Q3 launch plan. Engineering will "
            "own QA testing. Marketing will lead the launch email campaign.'"
        ),
    ),
    dict(
        task_label="math_reasoning_real",
        thinking_level="high",
        prompt=(
            "A train leaves at 9:15am traveling 60 mph along a straight track. "
            "A car leaves at 10:00am from the same station traveling 75 mph "
            "along the same route. At what time does the car catch up? "
            "Show your reasoning step by step."
        ),
    ),
]


def main() -> int:
    tk = ThinkletClient()
    if tk.demo_mode:
        print("[real_scale] WARNING: SDK is in demo mode. Set "
              "THINKLET_DEMO_MODE=false in .env to hit real Gemini.")
        # Continue anyway — the calls just go through the demo fallback.

    print(f"[real_scale] running {len(SCENARIOS)} originals...")
    for i, sc in enumerate(SCENARIOS, 1):
        r = tk.call(
            prompt=sc["prompt"],
            thinking_level=sc["thinking_level"],
            task_label=sc["task_label"],
        )
        print(
            f"  {i}. {sc['task_label']:<22} level={sc['thinking_level']:<6} "
            f"source={r.source} thinking={r.thinking_tokens} "
            f"out={r.output_tokens} text={(r.text or '')[:80]!r}"
        )
        # Brief space between originals so we don't burst Gemini.
        if i < len(SCENARIOS):
            time.sleep(1.5)

    tk.close()
    print()

    print("[real_scale] triggering /replay/run (re-runs each at lower levels)...")
    t0 = time.perf_counter()
    rep = httpx.post(f"{BACKEND}/replay/run", timeout=300.0).json()
    print(f"  -> {rep}  ({time.perf_counter() - t0:.1f}s)")

    print("[real_scale] triggering /judge/run (LLM compares responses)...")
    t0 = time.perf_counter()
    jud = httpx.post(f"{BACKEND}/judge/run", timeout=900.0).json()
    print(f"  -> {jud}  ({time.perf_counter() - t0:.1f}s)")
    print()

    # Pull the waste-map cells we just created.
    cells = httpx.get(f"{BACKEND}/waste-map", timeout=30.0).json()
    real_cells = [
        c for c in cells if c["task_label"].endswith("_real")
        or c["task_label"] == "image_caption_demo"
    ]
    print("[real_scale] Waste Map cells from this run:")
    print(f"  {'task_label':<22} {'orig':<7} {'rec':<7} {'verdict':<22} "
          f"{'color':<7} savings")
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*22} {'-'*7} {'-'*7}")
    for c in sorted(real_cells, key=lambda x: -x["estimated_savings_usd"]):
        rec = c["recommended_level"] or "—"
        print(
            f"  {c['task_label']:<22} {c['original_level']:<7} "
            f"{rec:<7} {c['verdict']:<22} {c['color']:<7} "
            f"${c['estimated_savings_usd']:.6f}"
        )

    print()
    print("Open http://localhost:5173 to see the full dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
