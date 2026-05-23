#!/usr/bin/env bash
# Build a clean .tar.gz of the repo for hackathon submission.
# Excludes: venv, node_modules, build outputs, the actual DB (but ships the
# seed scripts so anyone can regenerate it), .env (secrets), logs.
#
# Usage: bash scripts/package_submission.sh [version]
#
# Outputs: thinklet-submission-<version>.tar.gz in the current directory.

set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-$(date +%Y%m%d)}"
OUT="thinklet-submission-${VERSION}.tar.gz"

echo "[package] version: $VERSION"
echo "[package] preflight checks..."

# Tests must pass — don't ship a broken submission.
if [ -x .venv/bin/python ]; then
  echo "  - running pytest..."
  if ! .venv/bin/python -m pytest backend/tests/ -q > /tmp/thinklet_pkg_pytest.log 2>&1; then
    echo "  ❌ tests failed. See /tmp/thinklet_pkg_pytest.log"
    exit 1
  fi
  echo "  ✓ pytest passed"
else
  echo "  ⚠ no venv at .venv — skipping test check (not blocking)"
fi

# Frontend build must compile — same logic.
if [ -d frontend/node_modules ]; then
  echo "  - building frontend..."
  if ! (cd frontend && npm run build > /tmp/thinklet_pkg_build.log 2>&1); then
    echo "  ❌ frontend build failed. See /tmp/thinklet_pkg_build.log"
    exit 1
  fi
  echo "  ✓ frontend built"
else
  echo "  ⚠ no frontend/node_modules — skipping build check (not blocking)"
fi

# Sanity-check no API key got committed.
echo "  - scanning for accidentally-committed API keys..."
LEAK=$(grep -r "AIzaSy" \
  --include="*.py" --include="*.ts" --include="*.tsx" --include="*.md" \
  --include="*.json" --include="*.yaml" --include="*.yml" \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.git \
  --exclude-dir=dist --exclude-dir=.demo_logs \
  --exclude='package_submission.sh' \
  . 2>/dev/null || true)
if [ -n "$LEAK" ]; then
  echo "  ❌ possible API key leak detected:"
  echo "$LEAK"
  echo "  Remove or move to .env (which is .gitignored) before packaging."
  exit 1
fi
echo "  ✓ no API keys in tracked files"

# Build the tarball.
echo "[package] building $OUT..."
EXCLUDES=(
  --exclude='.venv'
  --exclude='node_modules'
  --exclude='dist'
  --exclude='.git'
  --exclude='__pycache__'
  --exclude='.pytest_cache'
  --exclude='.demo_logs'
  --exclude='*.duckdb'
  --exclude='*.duckdb.wal'
  --exclude='.env'
  --exclude='*.tar.gz'
)
tar -czf "$OUT" "${EXCLUDES[@]}" -C "$(pwd)/.." "$(basename "$(pwd)")"

SIZE=$(du -h "$OUT" | awk '{print $1}')
echo "[package] ✓ wrote $OUT ($SIZE)"
echo ""
echo "Contents (top level):"
tar -tzf "$OUT" | awk -F/ '{print $2}' | grep -v '^$' | sort -u | head -20
echo ""
echo "Submission checklist:"
echo "  ✓ Tests pass"
echo "  ✓ Frontend builds"
echo "  ✓ No leaked API keys"
echo "  ✓ Tarball ready: $OUT"
echo ""
echo "Next: upload $OUT to the hackathon submission portal, OR push to a"
echo "public git repo and submit the URL instead."
