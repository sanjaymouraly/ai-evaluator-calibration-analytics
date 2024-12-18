"""Report generation: CSV, JSON, PDF with provenance,
metric definitions, sample sizes, and generation timestamps.
Heavy generation runs as a background job."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Report
from app.services.analytics_engine import AnalyticsEngine

REPORTS_DIR = os.environ.get("REPORTS_DIR", "./reports")

METRIC_DEFINITIONS = {
    "cohen_kappa": (
        "Cohen's kappa: chance-corrected agreement between two raters "
        "on categorical labels. 1=perfect, 0=chance, <0=worse than chance. "
        "Undefined when both raters are constant on one category."
    ),
    "weighted_kappa": (
        "Quadratic weighted Cohen's kappa for ordinal scales: "
        "disagreements weighted by squared distance between levels."
    ),
    "fleiss_kappa": (
        "Fleiss' kappa: chance-corrected agreement for multiple raters "
        "per item; assumes a constant number of raters per item."
    ),
    "krippendorff_alpha": (
        "Krippendorff's alpha: chance-corrected disagreement accounting "
        "for missing data and multiple raters; level-specific metric "
        "(nominal/ordinal/interval/ratio). <0.667: tentative conclusions only."
    ),
    "icc_2_1": (
        "ICC(2,1): two-way random-effects intraclass correlation for "
        "absolute agreement, single rater; for interval/ratio scores only."
    ),
    "mad": "Mean absolute difference between paired numeric scores.",
    "raw_agreement": "Fraction of paired ratings that match exactly.",
    "accuracy_vs_gold": (
        "Fraction of ratings matching the expert-approved reference "
        "(gold) label. Measures correctness, not consistency."
    ),
    "reviewer_bias": (
        "Mean signed deviation of a reviewer's scores from the per-item "
        "consensus. Positive = severe, negative = lenient. Bias is "
        "distinct from (un)reliability."
    ),
    "calibration": (
        "Calibration: agreement between a reviewer's scores and "
        "expert-approved gold labels in a dedicated session, tracked "
        "across pre/post phases to measure improvement."
    ),
}


class ReportService:
    def __init__(self, db, analytics: AnalyticsEngine | None = None):
        self.db = db
        self.analytics = analytics or AnalyticsEngine(db)

    def build_payload(self, project_id: str, filters: dict | None = None) -> dict:
        engine = AnalyticsEngine(self.db)
        return {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "project_id": project_id,
            "filters": filters or {},
            "metric_definitions": METRIC_DEFINITIONS,
            "dashboard": engine.dashboard(project_id),
            "pairwise_agreement": engine.pairwise_reviewer_agreement(project_id),
            "reviewer_bias": engine.reviewer_bias(project_id),
            "accuracy_vs_gold": engine.accuracy_vs_gold(project_id),
            "score_distributions": engine.score_distributions(project_id),
            "disagreements": engine.disagreement_summary(project_id),
        }

    def to_csv(self, project_id: str) -> str:
        payload = self.build_payload(project_id)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["section", "key", "value"])
        dashboard = payload["dashboard"]
        writer.writerow(["progress", json.dumps(dashboard.get("progress"))])
        for cat_key, m in dashboard.get("metrics", {}).get("categories", {}).items():
            for k, v in m.items():
                writer.writerow([f"category.{cat_key}", k, v])
        writer.writerow(["disagreements", json.dumps(payload["disagreements"])])
        return buf.getvalue()

    def to_json(self, project_id: str) -> str:
        return json.dumps(self.build_payload(project_id), indent=2, default=str)

    def to_pdf(self, project_id: str, title: str = "Evaluation Report") -> bytes:
        payload = self.build_payload(project_id)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=LETTER)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 0.2 * inch))
        story.append(
            Paragraph(
                f"Generated: {payload['generated_at']} · Project: {project_id}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.3 * inch))

        progress = payload["dashboard"]["progress"]
        story.append(Paragraph("Progress", styles["Heading2"]))
        story.append(_table([["Metric", "Value"]] + [[k, str(v)] for k, v in progress.items()]))

        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph("Reliability by rubric category", styles["Heading2"]))
        rows = [["Category", "Metric", "Value", "N items"]]
        for key, m in payload["dashboard"]["metrics"].get("categories", {}).items():
            for mk in ("fleiss_kappa", "krippendorff_alpha", "icc_2_1", "raw_agreement", "mad"):
                if mk in m:
                    rows.append([key, mk, f"{m[mk]:.3f}" if m[mk] is not None else "n/a", str(m["n_items"])])
        story.append(_table(rows))

        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph("Disagreements", styles["Heading2"]))
        dg = payload["dashboard"]["disagreements"]
        story.append(_table([["Class", "Count"]] + [[k, str(v)] for k, v in dg.get("by_class", {}).items()]))

        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph("Metric definitions", styles["Heading2"]))
        for name, desc in METRIC_DEFINITIONS.items():
            story.append(Paragraph(f"<b>{name}</b>: {desc}", styles["BodyText"]))

        doc.build(story)
        return buf.getvalue()


def _table(data: list[list[str]]) -> Table:
    t = Table(data, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ]
        )
    )
    return t


def save_report_file(project_id: str, fmt: str, content: str | bytes) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(REPORTS_DIR, f"{project_id}_{stamp}.{fmt}")
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as f:
        f.write(content)
    return path


def register_report(
    db,
    project_id: str,
    title: str,
    fmt: str,
    filters: dict | None,
    path: str,
    user_id: str,
) -> Report:
    report = Report(
        project_id=project_id,
        title=title,
        report_format=fmt,
        filters_json=filters,
        metric_definitions_json=METRIC_DEFINITIONS,
        file_path=path,
        generated_by=user_id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
