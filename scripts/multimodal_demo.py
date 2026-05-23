"""Multimodal demo: send a vision-language call through the SDK.

Demonstrates that Thinklet captures multimodal calls (text + image) the same
way as text-only ones — including the *hidden thinking-token burn*, which is
exactly the waste pattern the dashboard surfaces.

Runs in demo mode by default (no Gemini API call) so you can verify the
ingest/replay/judge plumbing without spending money. Set
THINKLET_DEMO_MODE=false and GEMINI_API_KEY=... in .env to hit real Gemini.

Two calls are made: the same caption-this-image prompt at HIGH and MINIMAL.
The expected story: HIGH burns ~2,800 thinking tokens to caption an 8x8 png;
MINIMAL burns 0; the dashboard reveals it as `equivalent` and flags the
HIGH as wasted.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "sdk"))

from thinklet_sdk import ThinkletClient  # noqa: E402

# A 1x1 transparent PNG. 67 bytes — small enough to inline anywhere.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
    "DUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def main() -> int:
    tk = ThinkletClient()

    image_bytes = base64.b64decode(TINY_PNG_B64)

    # Gemini-native contents shape: list of {"text": ...} and
    # {"inline_data": {"mime_type", "data"}} dicts.
    contents = [
        {"text": "Describe this image in one short sentence."},
        {"inline_data": {"mime_type": "image/png", "data": image_bytes}},
    ]

    for level in ("high", "minimal"):
        r = tk.call(
            contents=contents,
            thinking_level=level,
            task_label="image_caption_demo",
        )
        print(
            f"level={level:<7} source={r.source} span={r.span_id} "
            f"thinking={r.thinking_tokens} out={r.output_tokens} "
            f"text={r.text!r}"
        )

    tk.close()
    print()
    print("Next:")
    print("  curl -X POST localhost:8000/replay/run")
    print("  curl -X POST localhost:8000/judge/run")
    print("  open http://localhost:5173 -> 'image_caption_demo' cell")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
