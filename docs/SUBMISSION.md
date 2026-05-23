# Hackathon submission — shot list & checklist

The submission package needs **4 screenshots + 1 short screencast**. This
doc tells you exactly what to capture, when, and how.

Everything assumes the demo is running: `bash scripts/run_demo.sh` (or the
backend + Vite are already up on 8000 and 5173).

---

## 4 screenshots (in capture order)

**Tip:** macOS `Cmd-Shift-4` then space, then click the window. That captures
the active window with a drop shadow. Save into `docs/screenshots/`.

### Screenshot 1 — Headlines (`01_headlines.png`)

**What to capture:** the top of http://localhost:5173 — the page header
("Thinklet tells you when your agent thought too hard.") plus the "Audit a
call" panel **collapsed** (no audit yet) plus the four headline cards
("Calls audited", "Likely waste", "Wasted (3.6 days)", "Monthly projection").

**Why this slide:** it's the "what does this product do?" first impression.
Headline waste dollars + Demo Mode badge + the interactive panel sitting
right at the top say everything in one frame.

**Capture command:**
```bash
# Once the page is in the right state, in any terminal:
mkdir -p docs/screenshots
screencapture -W docs/screenshots/01_headlines.png   # click the browser window
```

---

### Screenshot 2 — Waste Map with confidence badges (`02_waste_map.png`)

**What to capture:** scroll down to the **Waste Map** section. Frame
should include 6–8 cells. The new "**22/22 equivalent**" green confidence
badges should be visible on the `classification`, `greeting`,
`summarization`, `extraction` cells.

**Why this slide:** proof that Thinklet's recommendations are
sample-size-aware ("N/N equivalent" is much more convincing than just "go
to MINIMAL"). And the multi-color grid lands the full taxonomy: red waste,
red risk, green justified, yellow uncertain.

**Capture command:**
```bash
screencapture -W docs/screenshots/02_waste_map.png
```

---

### Screenshot 3 — Try Thinklet DAG (`03_try_thinklet_dag.png`)

**What to capture:** scroll back to the top, run an audit so the DAG is
visible. Recommended prompt for the screenshot:

```
A train leaves Station A at 9:15am at 60mph heading east. A car leaves at 10:00am from the same station at 75mph heading east. At what exact time does the car catch up? Show your reasoning step by step.
```

…with `task_label = math_demo` and `thinking_level = HIGH`. Click Run audit
and wait for the progress log to finish (3–5s on paid tier).

Frame the screenshot to include:
- The progress log with all four "✓" lines
- The 4-column DAG (Original / Replays / Judge / Recommendation)
- The red **"save $0.00xxxx per call"** banner on the right

**Why this slide:** the single most counter-intuitive finding in the demo —
Gemini 3.5 Flash answers a multi-step math problem just as well at MINIMAL
as at HIGH. Reviewers see the DAG and immediately understand the product
mechanism.

**Capture command:**
```bash
screencapture -W docs/screenshots/03_try_thinklet_dag.png
```

---

### Screenshot 4 — Run history drawer (`04_drawer_history.png`)

**What to capture:** scroll back to the Waste Map. Click a multi-sample
cell — the **`classification`** cell is ideal (22 samples, all equivalent).
The drawer opens on the right.

Scroll the drawer to show:
- The original vs replay side-by-side comparison up top
- The verdict pill (`equivalent` 99%)
- The "**Audit history for this pattern (22 samples)**" table near the
  bottom, with the highlighted blue row showing which sample you clicked

**Why this slide:** demonstrates that Thinklet doesn't just report on one
audit — it gives you the history. Distinguishes "robust" patterns from
"flappy" ones at a glance. The 22/22 history is itself the credibility
proof.

**Capture command:**
```bash
screencapture -W docs/screenshots/04_drawer_history.png
```

---

## 90-second screencast script

Use **QuickTime → File → New Screen Recording** (or `Cmd-Shift-5` →
"Record Selected Portion"). Frame the browser window.

| Time | Action | What to say (or caption) |
|---|---|---|
| 0:00–0:08 | Page loaded, top of dashboard visible. Pause on the Demo Mode pill + headlines. | "Thinklet audits whether your Gemini agent thought too hard. Real-time numbers from a real 139-call audit." |
| 0:08–0:18 | Scroll down to the Waste Map. Point at the **22/22 equivalent** badge on `classification` and the green `coding_debug` cell. | "Sample-size aware: 22 out of 22 classification calls could have run at MINIMAL. Code-debug genuinely needed HIGH." |
| 0:18–0:28 | Click the `math_speed` red cell. Drawer opens. | "Click any cell to see the side-by-side. Same prompt at HIGH burned 924 hidden thinking tokens; at MINIMAL, zero — and the answer is the same: 1:00 PM." |
| 0:28–0:35 | Scroll the drawer to the "Audit history" section. | "Plus the full audit history for this pattern — distinguishes one-shot equivalents from robust ones." |
| 0:35–0:50 | Close drawer, scroll up to **Try Thinklet** panel. Type a prompt, click Run audit. | "Audit your own prompt live. Five seconds, end-to-end against real Gemini 3.5 Flash." |
| 0:50–1:10 | Wait for progress log + DAG to render. Point at the DAG. | "Original on the left, three replay budgets, judge verdicts, recommended downgrade with per-call savings." |
| 1:10–1:20 | Scroll to header. Click **Copy policy**. Show the green "Copied ✓" flash. Open a terminal, `pbpaste \| head`. | "One click exports a deployable Python policy. Drop into your agent config." |
| 1:20–1:30 | Cut to the GitHub repo / final slide. | "Built in 24 hours. Code at &lt;your repo URL&gt;." |

Total: ~90 seconds. Save as `docs/screencast.mp4`.

---

## Submission checklist

Before you submit, run through this:

- [ ] All 4 screenshots saved to `docs/screenshots/`
- [ ] Screencast saved to `docs/screencast.mp4` (or hosted on Loom/YouTube)
- [ ] Backend tests pass: `.venv/bin/python -m pytest backend/tests/ -q` (should be 22 passing)
- [ ] Frontend builds clean: `cd frontend && npm run build`
- [ ] README "Submission" section near the top has the screenshot embed
- [ ] `RELEASE.md` has the headline numbers and the surprise findings
- [ ] No API key in any committed file (`grep -r AIza --include='*.py' --include='*.md' --include='*.json' --exclude-dir=.venv --exclude-dir=node_modules` should be empty)
- [ ] `.env` is `.gitignore`'d
- [ ] Submission package built: `bash scripts/package_submission.sh` → produces `thinklet-submission.tar.gz`
- [ ] Repo pushed to a public GitHub URL (or the submission tarball uploaded)

## Final touch — clean reset before screenshots

If your DB has accumulated test data and the Waste Map is cluttered, reset
to a clean seeded state before capturing screenshots:

```bash
python scripts/reset_demo.py   # wipes data/thinklet.duckdb and re-seeds the 8 planted patterns
# Restart backend so it picks up the fresh DB
pkill -f "uvicorn backend.app.main"
bash scripts/run_demo.sh
```

After reset:
- Dashboard shows the 8 seeded cells with their clean confidence badges
- No leftover `try_it`, `cli_audit_smoke`, `ui_test_*` cells from earlier dev runs

Then run the Try Thinklet panel once (the `math_demo` audit) so screenshot
#3 has fresh DAG data.
