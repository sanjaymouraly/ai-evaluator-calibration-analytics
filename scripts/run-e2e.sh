#!/usr/bin/env bash
# Start backend + frontend from a clean database, run the Playwright E2E
# suite (which also regenerates docs/images screenshots), then stop services.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_LOG="$(mktemp)"
FRONTEND_LOG="$(mktemp)"

cleanup() {
  echo "→ stopping services"
  # npm/uvicorn spawn children; start them in their own process group and
  # terminate the whole group so no dev server is left bound to the port.
  for pid in "${FRONTEND_PID:-}" "${BACKEND_PID:-}"; do
    [ -n "$pid" ] || continue
    kill -TERM -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT

echo "→ resetting local SQLite database"
rm -f "$ROOT/backend/eval_platform.db" "$ROOT/backend/eval_platform.db-wal" "$ROOT/backend/eval_platform.db-shm"

echo "→ starting backend on :${BACKEND_PORT}"
(cd "$ROOT/backend" && setsid env JWT_SECRET_KEY="${JWT_SECRET_KEY:-e2e-local-secret-0123456789abcdef}" \
  python -m uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" --log-level warning) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "→ waiting for backend health"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/admin/health" >/dev/null 2>&1; then break; fi
  sleep 1
  if [ "$i" -eq 60 ]; then echo "backend failed to start"; tail -30 "$BACKEND_LOG"; exit 1; fi
done

echo "→ starting frontend on :${FRONTEND_PORT}"
(cd "$ROOT/frontend" && setsid env VITE_API_PROXY="http://127.0.0.1:${BACKEND_PORT}" npm run dev -- --port "${FRONTEND_PORT}") >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

echo "→ waiting for frontend"
for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then break; fi
  sleep 1
  if [ "$i" -eq 90 ]; then echo "frontend failed to start"; tail -30 "$FRONTEND_LOG"; exit 1; fi
done

echo "→ running Playwright E2E suite (captures docs/images screenshots)"
(cd "$ROOT/frontend" && E2E_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}" npx playwright test)

echo "✓ E2E complete"
