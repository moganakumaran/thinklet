"""90-second speed-run demo: 5 audits across the verdict taxonomy.

  1. sentiment_speed  HIGH  -> expect equivalent at MINIMAL (red)
  2. json_speed       HIGH  -> expect equivalent at MINIMAL (red, JSON-equal)
  3. math_speed       HIGH  -> expect HIGH justified         (green)
  4. tagline_speed    HIGH  -> expect uncertain              (yellow)
  5. image_speed      HIGH  -> expect equivalent at MINIMAL  (red multimodal)

For each prompt: capture -> replay -> judge -> fetch detail, then print a
combined summary table.
"""
from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

import httpx

BACKEND = "http://localhost:8000"

# 1x1 transparent PNG (same one used by multimodal_demo.py).
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
    "DUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)

PROMPTS = [
    dict(
        label="sentiment_speed",
        prompt='Sentiment of this review (one word): "Works as described, no complaints."',
        level="high",
        image=None,
        expected="🔴 equivalent at MINIMAL (deterministic 'positive')",
    ),
    dict(
        label="json_speed",
        prompt=(
            'Extract JSON {"name": str, "age": int} from: "Alice is 32 years old." '
            "Return only the JSON object."
        ),
        level="high",
        image=None,
        expected="🔴 equivalent at MINIMAL (JSON-equal)",
    ),
    dict(
        label="math_speed",
        prompt=(
            "A train leaves Station A at 9:15am at 60mph heading east. "
            "A car leaves at 10:00am from the same station at 75mph heading east. "
            "At what exact time does the car catch up? Show your reasoning step by step."
        ),
        level="high",
        image=None,
        expected="🟢 HIGH justified (degraded at lower)",
    ),
    dict(
        label="tagline_speed",
        prompt="Write a 3-line tagline for a coffee shop targeting remote workers.",
        level="high",
        image=None,
        expected="🟡 uncertain (creative outputs vary)",
    ),
    dict(
        label="image_speed",
        prompt="Describe this image in exactly one sentence.",
        level="high",
        image=base64.b64decode(TINY_PNG_B64),
        expected="🔴 multimodal equivalent at MINIMAL",
    ),
]


def fmt_cost(v: float) -> str:
    if v >= 1:
        return f"${v:.2f}"
    if v > 0:
        return f"${v:.6f}"
    return "$0"


def run_one(p: dict, client: httpx.Client) -> dict:
    files = {}
    data = {
        "prompt": p["prompt"],
        "thinking_level": p["level"],
        "task_label": p["label"],
        "model": "gemini-3.5-flash",
    }
    if p["image"]:
        files["image"] = ("test.png", p["image"], "image/png")

    t0 = time.perf_counter()
    r = client.post(f"{BACKEND}/audit/capture", data=data, files=files, timeout=120.0)
    r.raise_for_status()
    span = r.json()
    t_cap = time.perf_counter() - t0

    t0 = time.perf_counter()
    r = client.post(f"{BACKEND}/audit/{span['id']}/replay", timeout=180.0)
    r.raise_for_status()
    replay = r.json()
    t_rep = time.perf_counter() - t0

    t0 = time.perf_counter()
    r = client.post(f"{BACKEND}/audit/{span['id']}/judge", timeout=180.0)
    r.raise_for_status()
    judge = r.json()
    t_jud = time.perf_counter() - t0

    detail = client.get(f"{BACKEND}/spans/{span['id']}/detail", timeout=30.0).json()

    return {
        "span": span,
        "detail": detail,
        "timings": {"capture": t_cap, "replay": t_rep, "judge": t_jud},
        "replay_summary": replay,
        "judge_summary": judge,
    }


def best_savings(detail: dict) -> tuple[str, float, str | None]:
    """Return (verdict_color, total_savings_usd, recommended_level)."""
    equivs = [j for j in detail["judges"] if j["verdict"] == "equivalent" and j["estimated_savings_usd"] > 0]
    if equivs:
        # lowest-level equivalent = best downgrade
        equivs.sort(key=lambda j: {"minimal": 0, "low": 1, "medium": 2, "high": 3}[j["alternative_level"]])
        return ("red", equivs[0]["estimated_savings_usd"], equivs[0]["alternative_level"])
    if any(j["verdict"] == "materially_different" for j in detail["judges"]):
        return ("red-risk", 0.0, None)
    if any(j["verdict"] == "uncertain" for j in detail["judges"]):
        return ("yellow", 0.0, None)
    return ("green", 0.0, None)


def main() -> int:
    print(f"speed-run starting at {time.strftime('%H:%M:%S')}")
    print(f"5 prompts × (capture + replay + judge) = ~15 Gemini calls\n")
    results = []
    t_total = time.perf_counter()
    with httpx.Client() as client:
        for i, p in enumerate(PROMPTS, 1):
            print(f"[{i}/5] {p['label']:<18} ... ", end="", flush=True)
            try:
                res = run_one(p, client)
                total_t = sum(res["timings"].values())
                print(f"done in {total_t:.1f}s "
                      f"(cap {res['timings']['capture']:.1f}s, "
                      f"rep {res['timings']['replay']:.1f}s, "
                      f"jud {res['timings']['judge']:.1f}s)")
                results.append((p, res))
            except Exception as exc:
                print(f"FAILED: {exc}")
                results.append((p, None))

    elapsed = time.perf_counter() - t_total
    print(f"\nall done in {elapsed:.1f}s\n")

    # ---- summary table ----
    print("=" * 92)
    print(f"{'#':<3} {'label':<18} {'verdict':<12} {'orig→rec':<14} {'think@HIGH':<11} {'savings':<10} {'expected'}")
    print("=" * 92)
    for i, (p, res) in enumerate(results, 1):
        if res is None:
            print(f"{i:<3} {p['label']:<18} FAILED")
            continue
        color, savings, rec = best_savings(res["detail"])
        span = res["detail"]["span"]
        think = span["thinking_tokens"] or 0
        rec_label = f"HIGH→{rec.upper()}" if rec else "—"
        verdict_label = {
            "red": "🔴 waste",
            "red-risk": "🔴 risk",
            "yellow": "🟡 uncertain",
            "green": "🟢 justified",
        }[color]
        print(f"{i:<3} {p['label']:<18} {verdict_label:<12} {rec_label:<14} "
              f"{think:<11} {fmt_cost(savings):<10} {p['expected']}")
    print("=" * 92)

    # Total potential savings across all 5
    total_save = 0.0
    for p, res in results:
        if res:
            _, s, _ = best_savings(res["detail"])
            total_save += s
    print(f"\nTotal best-per-prompt savings across these 5 calls: {fmt_cost(total_save)}")
    print("Open http://localhost:5173 — refresh to see all 5 new cells in the Waste Map.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
