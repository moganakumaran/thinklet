"""10-line SDK smoke test — calls the SDK 3 times at different thinking levels
and prints the span IDs that landed in the backend."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "sdk"))

from thinklet_sdk import ThinkletClient  # noqa: E402

tk = ThinkletClient()
for level in ("minimal", "medium", "high"):
    r = tk.call(
        prompt="Reply with one word: ok.",
        model="gemini-3.5-flash",
        thinking_level=level,
        task_label="sdk_smoke",
    )
    print(f"level={level:<7} source={r.source} span_id={r.span_id} "
          f"thinking_tokens={r.thinking_tokens} latency_ms={r.latency_ms} "
          f"text={r.text!r}")
tk.close()
