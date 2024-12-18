# Contributing

Thanks for your interest in improving the AI Evaluator Calibration &
Disagreement Analytics platform. This document explains how to set up a
development environment, how we keep quality high, and what we look for in a
pull request.

## Development setup

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# frontend
cd ../frontend
npm install
```

Run both servers (see `README.md` for details), then:

```bash
make test          # backend pytest + frontend vitest
make test-e2e      # Playwright end-to-end (needs both servers running)
make lint          # ruff + eslint
make typecheck     # mypy (statistics core) + tsc
```

## What we check in CI

| Check | Command | Scope |
| --- | --- | --- |
| Backend lint | `ruff check .` | all backend Python |
| Backend format | `ruff format --check .` | all backend Python |
| Backend types | `mypy` | `app/analytics` (statistics core) |
| Backend tests | `python -m pytest -q` | unit + API integration |
| Frontend types | `npx tsc --noEmit` | all TS/TSX |
| Frontend lint | `npx eslint . --ext ts,tsx` | all TS/TSX |
| Frontend tests | `npx vitest run` | unit/component |
| Frontend build | `npm run build` | production bundle |
| E2E | `npx playwright test` | full user journeys + screenshots |

## Conventions

- **Statistics must be validated.** Any change to `backend/app/analytics/`
  must include or update a test with a hand-computed reference value
  (see `backend/tests/test_stats.py`). If a metric is undefined for some
  input, it must return `None` plus a human-readable warning — never a
  fabricated number.
- **Never mutate submitted ratings.** Corrections append a new versioned row
  (`Rating.version`, `is_current`). Keep that invariant.
- **Rubric changes require human approval.** Any new code path that alters a
  rubric must go through `RubricChangeRequest` and produce a new version;
  historical ratings must keep referencing their original rubric version.
- **No secrets.** Never commit keys, tokens, or `.env` files. API keys are
  encrypted at rest and masked in all API responses and logs.
- **UI must degrade gracefully.** Empty states, loading indicators and
  retryable error states are part of the feature, not optional polish.

## Commit & PR process

1. Fork and create a topic branch.
2. Keep PRs focused; include tests for behaviour changes.
3. Run the full local suite (`make test`, `make lint`, `make typecheck`).
4. If you changed the UI, re-run `scripts/run-e2e.sh` so
   `docs/images/` screenshots stay truthful.
5. Describe the *why*, not just the *what*, in the PR description.

We may ask for changes before merging. That is normal and part of keeping an
evaluation platform trustworthy.
