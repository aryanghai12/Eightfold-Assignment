"""Recruiter CSV extractor (structured source).

Expected columns (case-insensitive, extra columns ignored): name, email, phone,
current_company, title. Missing columns are fine. Each row becomes one SourceRecord.
Raw values are emitted as-is; normalization happens later.
"""
from __future__ import annotations

import csv

from ..models import SourceRecord
from .base import Extractor

# Map our canonical concept -> the set of header spellings we accept for it.
_COLUMN_ALIASES = {
    "name": {"name", "full_name", "candidate", "candidate_name"},
    "email": {"email", "e-mail", "email_address"},
    "phone": {"phone", "phone_number", "mobile", "tel"},
    "current_company": {"current_company", "company", "employer", "organization"},
    "title": {"title", "job_title", "role", "position"},
}


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    """Return {canonical_concept: actual_header} for the headers present in the file."""
    resolved = {}
    lower_to_actual = {h.strip().lower(): h for h in (fieldnames or []) if h}
    for concept, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_to_actual:
                resolved[concept] = lower_to_actual[alias]
                break
    return resolved


class RecruiterCSVExtractor(Extractor):
    source_type = "recruiter_csv"

    def extract(self, path: str) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        src = self.source_id(path)
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                cols = _resolve_columns(reader.fieldnames or [])
                for row in reader:
                    rec = self._row_to_record(row, cols, src)
                    if rec.claims:
                        records.append(rec)
        except (OSError, csv.Error):
            return records  # degrade gracefully: return whatever parsed before the error
        return records

    def _row_to_record(self, row: dict, cols: dict, src: str) -> SourceRecord:
        rec = SourceRecord(source=src)

        def cell(concept: str) -> str | None:
            col = cols.get(concept)
            return (row.get(col) or "").strip() if col else None

        name = cell("name")
        rec.add("full_name", name, method="csv_column")

        # email/phone columns may contain multiple values separated by ; or |
        for raw_email in _split_multi(cell("email")):
            rec.add("emails", raw_email, method="csv_column")
        for raw_phone in _split_multi(cell("phone")):
            rec.add("phones", raw_phone, method="csv_column")

        company = cell("current_company")
        title = cell("title")
        if title:
            rec.add("headline", title, method="csv_column")
        if company or title:
            rec.add("experience", {"company": company, "title": title,
                                   "start": None, "end": "present", "summary": None},
                    method="csv_column")

        # Identity hints used by the merge stage to group records across sources.
        rec.match_hints = {"emails": [e for e in _split_multi(cell("email"))], "name": name}
        return rec


def _split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [p.strip() for p in value.replace("|", ";").replace(",", ";").split(";")]
    return [p for p in parts if p]
