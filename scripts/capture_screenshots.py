"""Automated screenshot capture for the hackathon submission.

Drives a headless Chromium via Playwright to produce the 4 submission
screenshots reproducibly. Run any time you tweak the UI and need fresh
captures.

Setup (one-time, ~80MB Chromium download):
    .venv/bin/pip install playwright
    .venv/bin/python -m playwright install chromium

Run (after starting the demo):
    bash scripts/run_demo.sh    # in another terminal
    .venv/bin/python scripts/capture_screenshots.py

Outputs:
    docs/screenshots/01_headlines.png
    docs/screenshots/02_waste_map.png
    docs/screenshots/03_try_thinklet_dag.png
    docs/screenshots/04_drawer_history.png
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
DASHBOARD_URL = "http://localhost:5173"

MATH_PROMPT = (
    "A train leaves Station A at 9:15am at 60mph heading east. "
    "A car leaves at 10:00am from the same station at 75mph heading east. "
    "At what exact time does the car catch up? Show your reasoning step by step."
)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("error: playwright not installed.", file=sys.stderr)
        print("  .venv/bin/pip install playwright", file=sys.stderr)
        print("  .venv/bin/python -m playwright install chromium", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            device_scale_factor=2,  # crisp retina-quality output
        )
        page = ctx.new_page()
        print(f"opening {DASHBOARD_URL}...")
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)

        # Wait for the waste-map to render (signals the dashboard finished
        # loading all its data).
        page.wait_for_selector(".map-grid", state="visible", timeout=15000)
        page.wait_for_timeout(800)  # let charts settle

        # ---- Screenshot 1: headlines (top of the page) ----
        print("[1/4] capturing 01_headlines.png ...")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        page.screenshot(
            path=str(OUT_DIR / "01_headlines.png"),
            clip={"x": 0, "y": 0, "width": 1440, "height": 1100},
        )

        # ---- Screenshot 2: Waste Map ----
        print("[2/4] capturing 02_waste_map.png ...")
        # Scroll the Waste Map section into view.
        page.evaluate("""
            const heads = Array.from(document.querySelectorAll('h2'));
            const target = heads.find(h => h.textContent.trim() === 'Waste Map');
            if (target) target.scrollIntoView({behavior: 'instant', block: 'start'});
        """)
        page.wait_for_timeout(400)
        page.screenshot(
            path=str(OUT_DIR / "02_waste_map.png"),
            clip={"x": 0, "y": 0, "width": 1440, "height": 1100},
        )

        # ---- Screenshot 3: Try Thinklet DAG (after running an audit) ----
        print("[3/4] running math audit + capturing 03_try_thinklet_dag.png ...")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)

        # Fill the prompt textarea.
        textarea = page.locator(".try-thinklet textarea").first
        textarea.fill(MATH_PROMPT)

        # Set task label.
        label_input = page.locator(".try-thinklet input[type='text']").first
        label_input.fill("math_demo_shot")

        # Click Run audit.
        run_btn = page.get_by_role("button", name="Run audit")
        run_btn.click()
        print("  waiting for audit to complete...")

        # The DAG only appears once the audit finishes. Wait for the
        # AuditDAG container (.audit-dag) to appear, with generous timeout
        # for free-tier pacing.
        page.wait_for_selector(".audit-dag", state="visible", timeout=180000)
        page.wait_for_timeout(800)  # let any final layout settle

        # Scroll the audit area to fit progress log + DAG in one shot.
        page.evaluate("""
            const dag = document.querySelector('.audit-dag-title');
            if (dag) dag.scrollIntoView({behavior: 'instant', block: 'start'});
            window.scrollBy(0, -200);  // small offset so the progress log is visible
        """)
        page.wait_for_timeout(400)
        page.screenshot(
            path=str(OUT_DIR / "03_try_thinklet_dag.png"),
            clip={"x": 0, "y": 0, "width": 1440, "height": 1100},
        )

        # ---- Screenshot 4: drawer with run history ----
        print("[4/4] capturing 04_drawer_history.png ...")
        # Scroll to the Waste Map again.
        page.evaluate("""
            const heads = Array.from(document.querySelectorAll('h2'));
            const target = heads.find(h => h.textContent.trim() === 'Waste Map');
            if (target) target.scrollIntoView({behavior: 'instant', block: 'start'});
        """)
        page.wait_for_timeout(300)

        # Click the 'classification' map cell (it has 22 samples in seed data).
        cell = page.locator(".map-cell").filter(has_text="classification").first
        cell.click()

        # Wait for the drawer to render.
        page.wait_for_selector(".drawer", state="visible", timeout=10000)
        page.wait_for_timeout(800)

        # Scroll the drawer so the audit history table is in view if possible.
        page.evaluate("""
            const drawer = document.querySelector('.drawer');
            if (drawer) {
                const headers = drawer.querySelectorAll('h2');
                for (const h of headers) {
                    if (h.textContent.includes('history')) {
                        h.scrollIntoView({behavior: 'instant', block: 'center'});
                        break;
                    }
                }
            }
        """)
        page.wait_for_timeout(400)
        page.screenshot(
            path=str(OUT_DIR / "04_drawer_history.png"),
            clip={"x": 0, "y": 0, "width": 1440, "height": 1100},
        )

        browser.close()

    print()
    print("✓ All 4 screenshots saved to docs/screenshots/")
    for f in sorted(OUT_DIR.glob("*.png")):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
