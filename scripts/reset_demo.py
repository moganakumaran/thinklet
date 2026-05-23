"""Wipe data/thinklet.duckdb and re-seed.

Used by run_demo.sh and any time the dashboard story drifts during a demo.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.db import _resolve_db_path, connect  # noqa: E402
from backend.app.seed import generate_demo_data  # noqa: E402


def main() -> int:
    db_path = _resolve_db_path()
    if db_path.exists():
        db_path.unlink()
        print(f"[reset] removed {db_path}")
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        wal.unlink()
    con = connect()
    counts = generate_demo_data(con)
    print("[reset] re-seeded: %(spans)s spans / %(replays)s replays / "
          "%(judges)s judges" % counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
