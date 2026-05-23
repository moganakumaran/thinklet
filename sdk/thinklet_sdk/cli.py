"""thinklet CLI — drive the auditor from any shell, no Python required.

Subcommands:
  thinklet audit <prompt>            single-prompt audit + DAG summary
  thinklet audit-csv <file.csv>      bulk audit from CSV (prompt,task_label,level)
  thinklet report                    print waste-report headlines
  thinklet policy [--format ...]     print recommended-level policy
  thinklet health                    quick health check

All commands talk HTTP to the backend at THINKLET_BACKEND_URL
(default http://localhost:8000). The backend must already be running.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("thinklet CLI requires httpx. Install: pip install httpx", file=sys.stderr)
    sys.exit(2)


def _backend() -> str:
    return os.environ.get("THINKLET_BACKEND_URL", "http://localhost:8000")


def _fmt_cost(v: float) -> str:
    return f"${v:.2f}" if v >= 1 else (f"${v:.6f}" if v > 0 else "$0")


def _audit_one(prompt: str, level: str, task_label: str, model: str,
               image_path: Path | None = None) -> dict[str, Any]:
    """Run capture -> replay -> judge -> detail for one prompt."""
    data = {
        "prompt": prompt,
        "thinking_level": level,
        "task_label": task_label,
        "model": model,
    }
    files = {}
    if image_path:
        files["image"] = (image_path.name, image_path.read_bytes(), "image/png")
    with httpx.Client(timeout=300.0) as c:
        r = c.post(f"{_backend()}/audit/capture", data=data, files=files or None)
        r.raise_for_status()
        span = r.json()
        sid = span["id"]
        c.post(f"{_backend()}/audit/{sid}/replay").raise_for_status()
        c.post(f"{_backend()}/audit/{sid}/judge").raise_for_status()
        detail = c.get(f"{_backend()}/spans/{sid}/detail").json()
    return detail


def _print_audit_summary(detail: dict[str, Any]) -> None:
    s = detail["span"]
    rank = {"minimal": 0, "low": 1, "medium": 2, "high": 3}
    print(f"  model:           {s['model']}")
    print(f"  level:           {s['thinking_level_used'].upper()}")
    print(f"  thinking tokens: {s.get('thinking_tokens')}")
    print(f"  cost:            {_fmt_cost(s['estimated_cost_usd'])}")
    print(f"  response:        {(s.get('response_redacted') or '')[:80]!r}")
    print()
    equivs = [j for j in detail["judges"]
              if j["verdict"] == "equivalent" and j["estimated_savings_usd"] > 0]
    if equivs:
        equivs.sort(key=lambda j: rank[j["alternative_level"]])
        best = equivs[0]
        print(f"  → recommended downgrade: {s['thinking_level_used'].upper()} → "
              f"{best['alternative_level'].upper()}")
        print(f"    saves {_fmt_cost(best['estimated_savings_usd'])} per call "
              f"(confidence {int(best['confidence'] * 100)}%)")
    else:
        risk = next((j for j in detail["judges"]
                     if j["verdict"] == "materially_different"), None)
        if risk:
            print(f"  ⚠ quality risk flagged at {risk['alternative_level'].upper()}")
        else:
            print(f"  → no safe downgrade detected (level was justified)")


def cmd_audit(args) -> int:
    prompt = args.prompt if args.prompt else sys.stdin.read().strip()
    if not prompt:
        print("error: no prompt provided", file=sys.stderr)
        return 1
    image_path = Path(args.image) if args.image else None
    if image_path and not image_path.exists():
        print(f"error: image file not found: {image_path}", file=sys.stderr)
        return 1
    print(f"auditing on {args.model} at {args.level.upper()}...")
    detail = _audit_one(prompt, args.level, args.task_label, args.model, image_path)
    _print_audit_summary(detail)
    return 0


def cmd_audit_csv(args) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"error: csv not found: {path}", file=sys.stderr)
        return 1
    rows: list[dict[str, str]] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "prompt" not in reader.fieldnames:
            print("error: csv must have a 'prompt' column "
                  "(optional: thinking_level, task_label, model)", file=sys.stderr)
            return 1
        for row in reader:
            rows.append(row)
    print(f"running {len(rows)} audits...")
    saved_total = 0.0
    rank = {"minimal": 0, "low": 1, "medium": 2, "high": 3}
    for i, row in enumerate(rows, 1):
        try:
            detail = _audit_one(
                row["prompt"],
                row.get("thinking_level") or args.level,
                row.get("task_label") or f"csv_{i}",
                row.get("model") or args.model,
            )
        except Exception as exc:
            print(f"  [{i}/{len(rows)}] FAILED: {exc}")
            continue
        eq = [j for j in detail["judges"]
              if j["verdict"] == "equivalent" and j["estimated_savings_usd"] > 0]
        if eq:
            eq.sort(key=lambda j: rank[j["alternative_level"]])
            saved_total += eq[0]["estimated_savings_usd"]
            label = (row.get("task_label") or f"csv_{i}")[:30]
            print(f"  [{i}/{len(rows)}] {label:<30} → {eq[0]['alternative_level']:<7} "
                  f"save {_fmt_cost(eq[0]['estimated_savings_usd'])}")
        else:
            label = (row.get("task_label") or f"csv_{i}")[:30]
            print(f"  [{i}/{len(rows)}] {label:<30} → keep as-is")
    print(f"\nTotal per-call savings if you applied every downgrade: {_fmt_cost(saved_total)}")
    return 0


def cmd_report(args) -> int:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{_backend()}/waste-report")
        r.raise_for_status()
        rep = r.json()
    print(f"audited:            {rep['total_calls_audited']}")
    print(f"with waste:         {rep['calls_with_likely_waste']}")
    print(f"wasted ({rep['observed_days']:.1f} days):  {_fmt_cost(rep['estimated_cost_wasted_usd'])}")
    print(f"monthly projection: {_fmt_cost(rep['monthly_projection_usd'])}")
    if rep["top_wasteful_patterns"]:
        print("\ntop wasteful patterns:")
        for p in rep["top_wasteful_patterns"][:5]:
            print(f"  {p['task_label']:<25} "
                  f"{p['calls_with_waste']:>4} calls  "
                  f"{p['typical_original_level']:<6} → {p['typical_recommended_level']:<7} "
                  f"{_fmt_cost(p['estimated_savings_usd'])}")
    if rep["recommended_downgrades"]:
        print("\nrecommended downgrades:")
        for d in rep["recommended_downgrades"][:5]:
            print(f"  {d['from_level']:<6} → {d['to_level']:<7} "
                  f"{d['affected_calls']:>4} calls  "
                  f"{_fmt_cost(d['estimated_savings_usd'])}")
    return 0


def cmd_policy(args) -> int:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{_backend()}/policy", params={"format": args.format})
        r.raise_for_status()
        if args.format == "json":
            obj = r.json()
            print(json.dumps(obj, indent=2))
        else:
            print(r.text)
    return 0


def cmd_health(args) -> int:
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{_backend()}/health")
            r.raise_for_status()
            h = r.json()
        print(f"backend: {_backend()}")
        print(f"  status:     {h['status']}")
        print(f"  demo_mode:  {h['demo_mode']}")
        print(f"  db_path:    {h['db_path']}")
        print(f"  span_count: {h['span_count']}")
        return 0
    except Exception as exc:
        print(f"backend unreachable at {_backend()}: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="thinklet",
                                description="Audit Gemini calls for thinking-budget waste.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # audit
    pa = sub.add_parser("audit", help="audit one prompt")
    pa.add_argument("prompt", nargs="?", help="prompt text (or pass via stdin)")
    pa.add_argument("--level", default="high", choices=["minimal", "low", "medium", "high"])
    pa.add_argument("--task-label", default="cli_audit")
    pa.add_argument("--model", default="gemini-3.5-flash")
    pa.add_argument("--image", default=None, help="path to image (multimodal)")
    pa.set_defaults(fn=cmd_audit)

    # audit-csv
    pc = sub.add_parser("audit-csv", help="bulk audit from CSV")
    pc.add_argument("file", help="path to .csv with at least a 'prompt' column")
    pc.add_argument("--level", default="high", choices=["minimal", "low", "medium", "high"])
    pc.add_argument("--model", default="gemini-3.5-flash")
    pc.set_defaults(fn=cmd_audit_csv)

    # report
    pr = sub.add_parser("report", help="show waste-report headlines")
    pr.set_defaults(fn=cmd_report)

    # policy
    pp = sub.add_parser("policy", help="export recommended-level policy")
    pp.add_argument("--format", default="python", choices=["json", "python", "yaml"])
    pp.set_defaults(fn=cmd_policy)

    # health
    ph = sub.add_parser("health", help="check if the backend is reachable")
    ph.set_defaults(fn=cmd_health)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
