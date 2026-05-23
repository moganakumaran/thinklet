"""Phase 0 sanity check: attempt one Gemini call at each thinking level.

Falls back gracefully with instructions if API access is unavailable.
Exit code 0 in both success and fallback paths so CI/dev setup is non-fatal.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

THINKING_LEVELS = ["minimal", "low", "medium", "high"]

DEFAULT_MODEL = "gemini-3.5-flash"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass


def _fallback(reason: str, already_demo: bool = False) -> int:
    print(f"[sanity] {reason}")
    if already_demo:
        print("[sanity] Demo mode is the primary demo path; nothing to verify against the real API.")
    else:
        print("[sanity] Falling back to demo mode — set THINKLET_DEMO_MODE=true in .env")
        print("[sanity] Demo dataset is the primary demo path; real API is optional.")
    return 0


def main() -> int:
    _load_env()

    if os.environ.get("THINKLET_DEMO_MODE", "").lower() == "true":
        return _fallback(
            "THINKLET_DEMO_MODE=true — skipping real API sanity check.",
            already_demo=True,
        )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return _fallback("GEMINI_API_KEY not set.")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return _fallback("google-genai not installed (pip install -r requirements.txt).")

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        return _fallback(f"Could not initialize Gemini client: {exc}")

    prompt = "Reply with exactly one word: ok."
    ok = True
    for level in THINKING_LEVELS:
        try:
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=level)
            )
            resp = client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=prompt,
                config=config,
            )
            text = getattr(resp, "text", "") or ""
            print(f"[sanity] {level:<8} -> {text.strip()[:60]!r}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[sanity] {level:<8} FAILED: {exc}")

    if not ok:
        return _fallback("One or more thinking levels failed.")

    print("[sanity] All thinking levels succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
