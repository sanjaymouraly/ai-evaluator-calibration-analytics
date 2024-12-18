# Example datasets

These small, hand-written files demonstrate every supported import path and
column alias. They are deliberately tiny so you can trace exactly what the
importer does.

| File | Format | Notes |
| --- | --- | --- |
| `sample_evaluations.csv` | CSV | Uses the canonical columns `prompt`, `response`, `model_name`, `reference_answer`. |
| `sample_evaluations.jsonl` | JSONL | One JSON object per line; same fields. |
| `sample_evaluations.json` | JSON | Array form (`[ {...}, {...} ]`) — also accepts `{"items": [...]}`. |

## Column aliases the importer auto-detects

| Canonical field | Accepted source columns |
| --- | --- |
| `external_id` | `external_id`, `id`, `item_id`, `task_id`, `case_id` |
| `prompt` | `prompt`, `question`, `input`, `query`, `instruction` |
| `response_a` | `response_a`, `response`, `answer`, `output`, `completion`, `model_output` |
| `response_b` | `response_b`, `response_2`, `alternative`, `output_b` |
| `reference_answer` | `reference_answer`, `gold_answer`, `reference`, `expected` |
| `model_name` | `model_name`, `model`, `llm`, `generator` |
| `model_version` | `model_version`, `version` |
| `language` | `language`, `lang` |
| `task_type` | `task_type`, `category`, `task` |

Any column that does not map is preserved as task metadata, so nothing is
silently dropped.

## Importing

1. Sign in and open a project → **Tasks & data** → **Import dataset**.
2. Choose the file (or paste its content).
3. Click **Validate (dry run)** first — you get a per-row preview with
   actionable errors and a duplicate count, and nothing is written.
4. Click **Import rows** to persist the valid rows.

Re-importing the same file is safe: rows already present (matched by
`external_id` or by content hash) are skipped, never overwritten.

## Larger demo dataset

For a fully populated scenario (60 tasks, 5 reviewers with distinct scoring
tendencies, gold labels, disagreements, adjudications and a calibration
session), use **Administration → Seed demo data** in the running application.
It is generated deterministically (fixed seed) so results are reproducible.
