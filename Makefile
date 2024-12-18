.PHONY: help install dev-backend dev-frontend dev test test-backend test-frontend test-e2e \
        lint lint-backend lint-frontend typecheck format migrate seed-demo reset-demo \
        smoke docker-up docker-down clean

help:
	@echo "AI Evaluator Calibration & Disagreement Analytics"
	@echo ""
	@echo "  make install        Install backend + frontend dependencies"
	@echo "  make dev-backend    Run the FastAPI backend on :8000 (SQLite)"
	@echo "  make dev-frontend   Run the Vite dev server on :5173"
	@echo "  make test           Run all backend + frontend unit/integration tests"
	@echo "  make test-e2e       Run Playwright end-to-end (needs both servers up)"
	@echo "  make lint           Ruff + ESLint"
	@echo "  make typecheck      mypy (backend core) + tsc (frontend)"
	@echo "  make format         Auto-format backend (ruff) "
	@echo "  make seed-demo      Seed the deterministic demo dataset (TOKEN=<admin token>)"
	@echo "  make reset-demo     Remove demo data (real data untouched)"
	@echo "  make smoke          API workflow smoke test against a running backend"
	@echo "  make docker-up      Start PostgreSQL + backend + frontend via compose"
	@echo "  make docker-down    Stop compose stack"
	@echo "  make clean          Remove caches, test artifacts and the local SQLite DB"

install:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install --no-audit --no-fund

dev-backend:
	cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev:
	@echo "Run in two terminals:  make dev-backend   and   make dev-frontend"

test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest -q

test-frontend:
	cd frontend && npx vitest run

test-e2e:
	cd frontend && npx playwright test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && ruff check . && ruff format --check .

lint-frontend:
	cd frontend && npx eslint . --ext ts,tsx

typecheck:
	cd backend && mypy
	cd frontend && npx tsc --noEmit

format:
	cd backend && ruff check --fix . && ruff format .

migrate:
	cd backend && alembic upgrade head

seed-demo:
	@if [ -z "$$TOKEN" ]; then \
	  echo "Set TOKEN to an admin access token, e.g."; \
	  echo "  TOKEN=\$$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \\"; \
	  echo "    -H 'Content-Type: application/json' \\"; \
	  echo "    -d '{\"email\":\"<admin>\",\"password\":\"<password>\"}' | python -c 'import json,sys; print(json.load(sys.stdin)[\"access_token\"])')"; \
	  exit 1; \
	fi
	@curl -s -X POST http://127.0.0.1:8000/api/admin/seed-demo \
	  -H "Authorization: Bearer $$TOKEN" | head -c 400; echo

reset-demo:
	@if [ -z "$$TOKEN" ]; then echo "Set TOKEN to an admin access token (see 'make seed-demo')."; exit 1; fi
	@curl -s -X POST http://127.0.0.1:8000/api/admin/reset-demo \
	  -H "Authorization: Bearer $$TOKEN" | head -c 200; echo

smoke:
	@echo "Runs the API workflow smoke test against SMOKE_BASE (default http://127.0.0.1:8000)"
	cd backend && python ../scripts/smoke_api.py

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache backend/__pycache__
	find . -type d -name __pycache__ -not -path "*/node_modules/*" -exec rm -rf {} +
	rm -rf frontend/test-results frontend/playwright-report
	rm -f backend/eval_platform.db backend/eval_platform.db-wal backend/eval_platform.db-shm
