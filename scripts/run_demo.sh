#!/usr/bin/env bash
# One-command end-to-end demo launcher.
#   - reset DB + re-seed (so the demo story is always the same)
#   - start backend (uvicorn) in background
#   - start frontend (vite) in background
#   - print URL
#   - trap SIGINT to clean up both
#
# Run: bash scripts/run_demo.sh
# Stop: Ctrl-C (the trap cleans up).

set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  echo "[demo] no venv at $VENV — creating one and installing deps..."
  python3.11 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[demo] wrote .env (demo mode default)"
fi

# Load .env so THINKLET_DEMO_MODE / GEMINI_API_KEY / etc. flow into uvicorn.
set -a
# shellcheck disable=SC1091
source .env
set +a

DEMO_MODE_LABEL="real"
if [ "${THINKLET_DEMO_MODE:-true}" = "true" ]; then
  DEMO_MODE_LABEL="demo"
fi

echo "[demo] mode: $DEMO_MODE_LABEL (THINKLET_DEMO_MODE=${THINKLET_DEMO_MODE:-true})"
echo "[demo] resetting + reseeding DB..."
"$PY" scripts/reset_demo.py

LOGDIR=".demo_logs"
mkdir -p "$LOGDIR"

echo "[demo] starting backend on :8000 ..."
"$PY" -m uvicorn backend.app.main:app \
  --port 8000 --log-level warning > "$LOGDIR/backend.log" 2>&1 &
BACKEND_PID=$!

# wait for backend health
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health | grep -q 200; then
    echo "[demo] backend up."
    break
  fi
  sleep 0.5
done

echo "[demo] starting frontend on :5173 ..."
(cd frontend && npm run dev > "../$LOGDIR/frontend.log" 2>&1) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "[demo] shutting down..."
  kill "$BACKEND_PID" 2>/dev/null || true
  kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "  ┌──────────────────────────────────────────────────────────┐"
echo "  │  Thinklet demo ready                                     │"
echo "  │  Open  http://localhost:5173                             │"
echo "  │  API   http://localhost:8000/health                      │"
echo "  │  Logs  $LOGDIR/backend.log, $LOGDIR/frontend.log         │"
echo "  │  Ctrl-C to stop both                                     │"
echo "  └──────────────────────────────────────────────────────────┘"
echo ""

wait
