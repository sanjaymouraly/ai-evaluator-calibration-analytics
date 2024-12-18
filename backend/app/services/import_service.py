"""Dataset import service: CSV / JSON / JSONL with schema mapping,
validation, previews, actionable errors, duplicate detection, and safe
re-import (existing items matched by external_id are skipped, never
duplicated silently).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any

from sqlalchemy.orm import Session

from app.exceptions import ValidationError
from app.models import Dataset, EvaluationTask, Project
from app.schemas import ImportPreviewRow, ImportResult

MAX_ROWS = 50_000
MAX_FIELD_CHARS = 100_000

CANONICAL_FIELDS = {
    "external_id": ["external_id", "id", "item_id", "task_id", "case_id"],
    "prompt": ["prompt", "question", "input", "query", "instruction"],
    "response_a": ["response_a", "response", "answer", "output", "completion", "model_output"],
    "response_b": ["response_b", "response_2", "alternative", "output_b"],
    "reference_answer": ["reference_answer", "gold_answer", "reference", "expected"],
    "model_name": ["model_name", "model", "llm", "generator"],
    "model_version": ["model_version", "version"],
    "language": ["language", "lang"],
    "task_type": ["task_type", "category", "task"],
}


def _hash_task(item: dict[str, Any]) -> str:
    stable = json.dumps(
        {k: item.get(k) for k in ("prompt", "response_a", "response_b", "model_name")},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(stable.encode()).hexdigest()


class ImportService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- parsing ----------------
    def parse(self, filename: str, file_format: str, content: str) -> list[dict]:
        if len(content.encode("utf-8")) > 60 * 1024 * 1024:
            raise ValidationError("File too large (max 60 MB of text).")
        if file_format == "csv":
            return self._parse_csv(content)
        if file_format == "json":
            return self._parse_json(content)
        if file_format == "jsonl":
            return self._parse_jsonl(content)
        raise ValidationError("Unsupported format; use csv, json, or jsonl.")

    def _parse_csv(self, content: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                break
            rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k})
        return rows

    def _parse_json(self, content: str) -> list[dict]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}") from exc
        if isinstance(data, dict):
            for key in ("items", "tasks", "data", "records", "examples"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                data = [data]
        if not isinstance(data, list):
            raise ValidationError("JSON must contain an array of items (or an object with an 'items' array).")
        return data[:MAX_ROWS]

    def _parse_jsonl(self, content: str) -> list[dict]:
        rows = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Invalid JSONL line {len(rows) + 1}: {exc.msg}") from exc
        return rows[:MAX_ROWS]

    # ---------------- mapping ----------------
    def infer_mapping(self, columns: list[str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        lowered = {c.strip().lower(): c for c in columns}
        for canonical, aliases in CANONICAL_FIELDS.items():
            for alias in aliases:
                if alias in lowered:
                    mapping[canonical] = lowered[alias]
                    break
        return mapping

    def apply_mapping(self, rows: list[dict], mapping: dict[str, str]) -> list[dict]:
        out = []
        for row in rows:
            item: dict[str, Any] = {}
            for canonical, src in mapping.items():
                if src in row and row[src] not in (None, ""):
                    item[canonical] = row[src]
            # unmapped columns become metadata
            extra = {k: v for k, v in row.items() if k not in mapping.values() and v not in (None, "")}
            if extra:
                item["metadata"] = extra
            out.append(item)
        return out

    # ---------------- validation ----------------
    @staticmethod
    def validate_row(item: dict[str, Any], project_mode: str) -> list[str]:
        errors: list[str] = []
        prompt = str(item.get("prompt") or "")
        resp_a = str(item.get("response_a") or "")
        if not prompt.strip():
            errors.append("missing required field: prompt")
        if not resp_a.strip():
            errors.append("missing required field: response_a")
        if project_mode == "pairwise" and not (item.get("response_b") or "").strip():
            errors.append("pairwise mode requires response_b")
        if len(prompt) > MAX_FIELD_CHARS or len(resp_a) > MAX_FIELD_CHARS:
            errors.append("field exceeds maximum length")
        return errors

    # ---------------- import pipeline ----------------
    def import_dataset(
        self,
        project: Project,
        name: str,
        filename: str,
        file_format: str,
        content: str,
        mapping: dict[str, str] | None,
        dry_run: bool,
        created_by: str,
    ) -> ImportResult:
        rows = self.parse(filename, file_format, content)
        columns = list(rows[0].keys()) if rows else []
        if mapping is None:
            mapping = self.infer_mapping(columns)
        items = self.apply_mapping(rows, mapping)

        preview: list[ImportPreviewRow] = []
        errors: list[dict[str, Any]] = []
        existing_hashes = {
            h
            for (h,) in self.db.query(EvaluationTask.import_hash)
            .filter(EvaluationTask.project_id == project.id)
            .filter(EvaluationTask.import_hash.isnot(None))
        }
        existing_external = {
            ext
            for (ext,) in self.db.query(EvaluationTask.external_id)
            .filter(EvaluationTask.project_id == project.id)
            .filter(EvaluationTask.external_id.isnot(None))
        }

        valid_items: list[EvaluationTask] = []
        seen_hashes_in_batch: set[str] = set()
        duplicates = 0

        for i, item in enumerate(items):
            row_errors = self.validate_row(item, project.mode)
            imp_hash = _hash_task(item)
            ext_id = str(item.get("external_id") or "").strip() or None
            if ext_id and ext_id in existing_external:
                duplicates += 1
                preview.append(
                    ImportPreviewRow(
                        row_number=i + 1,
                        valid=False,
                        errors=["duplicate external_id — skipped (safe re-import)"],
                        data=item,
                    )
                )
                continue
            if imp_hash in existing_hashes or imp_hash in seen_hashes_in_batch:
                duplicates += 1
                preview.append(
                    ImportPreviewRow(
                        row_number=i + 1, valid=False, errors=["duplicate content hash — skipped"], data=item
                    )
                )
                continue
            if row_errors:
                for e in row_errors:
                    errors.append({"row": i + 1, "error": e})
                preview.append(ImportPreviewRow(row_number=i + 1, valid=False, errors=row_errors, data=item))
                continue
            seen_hashes_in_batch.add(imp_hash)
            task = EvaluationTask(
                project_id=project.id,
                external_id=ext_id,
                mode=project.mode if item.get("response_b") is None else "pairwise",
                prompt=str(item["prompt"]),
                response_a=str(item["response_a"]),
                response_b=str(item["response_b"]) if item.get("response_b") else None,
                reference_answer=str(item["reference_answer"]) if item.get("reference_answer") else None,
                model_name=item.get("model_name"),
                model_version=item.get("model_version"),
                language=item.get("language"),
                task_type=item.get("task_type"),
                metadata_json=item.get("metadata"),
                import_hash=imp_hash,
            )
            valid_items.append(task)
            preview.append(ImportPreviewRow(row_number=i + 1, valid=True, errors=[], data=item))

        dataset = None
        if not dry_run and valid_items:
            dataset = Dataset(
                project_id=project.id,
                name=name,
                source_file_name=filename,
                source_format=file_format,
                import_errors_json=errors if errors else None,
                created_by=created_by,
            )
            self.db.add(dataset)
            self.db.flush()
            for task in valid_items:
                task.dataset_id = dataset.id
                self.db.add(task)
            self.db.commit()
            # Refresh status on project
            if project.status == "draft":
                project.status = "active"
                self.db.commit()

        return ImportResult(
            session_id=hashlib.sha256(f"{filename}{len(items)}".encode()).hexdigest()[:16],
            dataset_id=dataset.id if dataset else None,
            total_rows=len(items),
            valid_rows=len(valid_items),
            error_rows=len(errors),
            duplicates_skipped=duplicates,
            preview=preview[:200],
            errors=errors[:200],
            dry_run=dry_run,
        )
