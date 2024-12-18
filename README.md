# AI Evaluator Calibration & Disagreement Analytics

Measures evaluator calibration, disagreement, and reliability across AI grading runs.

## Features

- Multiple projects with draft → active → completed → archived lifecycle.
- Project membership with lead / reviewer / adjudicator roles; strict project-level access control.
- CSV / JSON / JSONL import with column-alias auto-mapping, dry-run validation, per-row errors, duplicate detection and safe re-import.
- Single-response and pairwise comparison modes.
- Rubrics with categorical / ordinal / numerical scales, weights, definitions, guidance, scoring anchors and examples; full versioning.
- Reviewer assignment with workload balancing and conflict-of-interest exclusion; blinded independent rating; draft autosave; abstentions.
- Immutable rating history — corrections append versions, never overwrite.

## Stack

Python, Node.js, FastAPI, Uvicorn, SQLAlchemy, Pydantic, NumPy, ReportLab, HTTPX, pytest

## Clone

```bash
git clone https://github.com/sanjaymouraly/ai-evaluator-calibration-analytics.git
cd ai-evaluator-calibration-analytics
```

## Setup

```bash
# The project ships a Docker Compose setup.
docker compose up --build
```

See `docs/` or the compose file for environment variables and ports.

## Run

```bash
docker compose up --build
```

## Tests

```bash
pytest -q
```

## Notes

- Sample data, when included, is synthetic.

## License

MIT © 2024 [Sanjay Mouraly](https://github.com/sanjaymouraly)
