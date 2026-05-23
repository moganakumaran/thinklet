"""Top-level seed launcher.

Run: python scripts/seed_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.db import connect  # noqa: E402
from backend.app.seed import generate_demo_data  # noqa: E402


def main() -> int:
    con = connect()
    counts = generate_demo_data(con)
    print(
        "[seed] OK — spans=%(spans)s replay_results=%(replays)s "
        "judge_results=%(judges)s replay_jobs=%(replay_jobs)s" % counts
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
