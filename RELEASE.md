# Thinklet v0.1.0 — Release notes

> Thinklet tells you when your agent thought too hard.

## What shipped

A working, demo-able auditor for Gemini thinking-budget waste, with an
interactive dashboard and CLI. Built as a 24-hour hackathon MVP, then
extended with multimodal support, real-Gemini wiring, and six day-of-work
polish items.

## Headline numbers (from the actual run that produced this release)

```
Backend tests:                     22/22 passing
Frontend build:                    clean (542 KB gzipped)
Models tested:                     gemini-3.5-flash, gemini-2.5-flash
Seeded planted patterns:           8 (120 spans / 335 replays / 335 judges)
Real-Gemini audits performed:      19 captures, 23 replays, 14 judges
Time-to-audit (paid tier):         ~3-5 seconds per prompt
Time-to-audit (free tier paced):   ~80-100 seconds per prompt
End-to-end speed-run demo:         5 prompts, 15 Gemini calls, 90.9 seconds
```

## The single best finding (real data, real Gemini 3.5)

**Multi-step math at HIGH thinking_budget burns 924 hidden tokens. The same
prompt at MINIMAL (`thinking_budget=0`) burns 0 tokens — and gets the same
correct answer.** Adaptive thinking calibrates spend to the budget you set;
only MINIMAL is a hard switch.

```
Level     budget    thinking_burned   answer    cost
HIGH      24,576    924               1:00 PM   $0.003826
MEDIUM     4,096    919               1:00 PM   $0.004076  ← MORE than HIGH
LOW        1,024    815               1:00 PM   $0.003658
MINIMAL        0      0               1:00 PM   $0.001383  ← 64% cheaper
```

The "savings" intuition you'd reach without measuring (LOW or MEDIUM should
save money) is **wrong**. Only Thinklet's measurement reveals this.

## Feature surface

### Core (MVP scope)

- ✅ SDK wrapper around `google-genai` with prompt-hash + `usage_metadata`
  extraction
- ✅ FastAPI backend + DuckDB single-file store
- ✅ Replay engine — fans out to lower thinking budgets, idempotent, paced
- ✅ Judge — deterministic-first (exact / JSON / numeric), LLM fallback with
  3-vote majority
- ✅ React dashboard: Waste Report, Waste Map (red/green/yellow), Trace
  Feed, drill-down drawer
- ✅ 8 planted seed patterns covering the full verdict taxonomy
- ✅ One-command demo (`bash scripts/run_demo.sh`)

### Beyond MVP (shipped same day)

- ✅ **Multimodal support** — `tk.call(contents=[…])` with image bytes,
  same DAG, image bytes round-trip through `contents_json` in DuckDB
- ✅ **Real Gemini 3.5 Flash integration** — `thinking_budget` integer
  mapping; tested live with real API key
- ✅ **Interactive Try Thinklet UI** — type a prompt + optional image
  upload, click Run audit, watch step-by-step progress, see the DAG
- ✅ Rate-limit pacing knobs (`THINKLET_REPLAY_SLEEP_S`,
  `THINKLET_JUDGE_VOTE_SLEEP_S`, `THINKLET_JUDGE_VOTES`)

### Day-of-work improvements (6 items)

- ✅ **Upward replay fan-out** for MINIMAL spans (quality risk detection
  works in live mode, not just seed data)
- ✅ **Retry-with-backoff on 429s** with server-reported `retryDelay`
  parsing
- ✅ **Sample-size aware confidence** — "22/22 equivalent" badges on
  Waste Map cells
- ✅ **Run history per cell** — drawer shows all spans matching the cell,
  highlights the current one
- ✅ **Policy export** — `GET /policy?format=python|yaml|json` plus header
  buttons (Copy / Open)
- ✅ **CLI** — `thinklet audit / audit-csv / report / policy / health`

### Documentation

- ✅ `README.md` — quick start, demo path, architecture diagram, env vars
- ✅ `docs/THINKLET.md` — 806-line deep dive: architecture, design,
  9 use cases, value quantification, limitations
- ✅ `docs/SUBMISSION.md` — screenshot shot list + screencast script

## Files / surfaces

```
backend/         ~ 1,200 lines (app/) + ~ 250 lines (tests/)
sdk/             ~ 450 lines (Python SDK + CLI)
frontend/src/    ~ 950 lines (TS + TSX)
scripts/         ~ 350 lines (bash + Python automation)
docs/            ~ 1,100 lines (markdown)
```

## Surprises encountered while building

1. **Gemini 2.5 Flash rejected `thinking_level` (string)** — only the 3.x
   family accepts it. Used integer `thinking_budget` for forward
   compatibility.
2. **Free-tier Gemini is 5 RPM / 20 RPD** — much harsher than I assumed.
   Drove the design of the pacing env vars + the per-span scoped audit
   endpoints + the demo-mode fallback in the replay engine.
3. **DuckDB connections are not thread-safe** under FastAPI's worker pool —
   discovered when `con.execute("SELECT COUNT(*)").fetchone()` returned
   `None` under concurrent load. Fixed with per-request `con.cursor()`.
4. **Adaptive thinking calibrates spend to the budget cap** — LOW (1024)
   burned 815, MEDIUM (4096) burned 919, HIGH (24576) burned 924 on the
   same prompt. Only MINIMAL (0) is a hard switch. This is the most
   important Thinklet finding in the demo data.

## Known limitations

See `docs/THINKLET.md` § 11 for the full list. The big four:

- No auth/multi-tenancy — single-user local deploy
- LLM judge can be wrong; mitigated with deterministic-first + 3-vote
  majority + `uncertain` bucket
- Image bytes are stored inline in DuckDB (`contents_json`) — fine for
  demos, bloats DB on large multimodal corpora
- Free-tier rate limits force ~80s audit cycles; paid tier drops this to
  ~3-5 s

## What's next (post-hackathon)

Top-3 items from the improvement backlog:

1. **OpenTelemetry exporter** — accept OTEL `gen_ai` spans; removes the
   SDK-instrumentation requirement
2. **Anthropic + OpenAI provider support** — same audit shape for Claude's
   `thinking` mode and OpenAI's `reasoning_effort`
3. **Background workers + streaming progress** — production-grade UX for
   long audits

## Acknowledgments

Built solo in a single 24-hour window. Tools: Claude Code as the
engineering partner; `google-genai` Python SDK; FastAPI; DuckDB; React +
Vite + Recharts; the Gemini 3.5 Flash API.
