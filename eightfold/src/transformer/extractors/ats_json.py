"""ATS JSON extractor (structured source, foreign schema).

The ATS uses its *own* field names that don't match ours (the whole point of this source):
e.g. `applicant_name`, `contact.email_address`, `skill_tags`, `history[].org`. We translate
those into canonical claims via an explicit, readable mapping. Nested/missing keys are
tolerated. A single blob may contain one candidate or a list under `candidates`/`results`.
"""
from __future__ import annotations

import json
from typing import Any

from ..handles import github_handle, linkedin_handle
from ..models import SourceRecord
from .base import Extractor


class ATSJSONExtractor(Extractor):
    source_type = "ats_json"

    def extract(self, path: str) -> list[SourceRecord]:
        src = self.source_id(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return []  # garbage/missing blob -> no records, no crash

        candidates = self._unwrap(data)
        records = []
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            rec = self._map_candidate(cand, src)
            if rec.claims:
                records.append(rec)
        return records

    @staticmethod
    def _unwrap(data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("candidates", "results", "applicants", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return []

    def _map_candidate(self, c: dict, src: str) -> SourceRecord:
        rec = SourceRecord(source=src)
        g = _Getter(c)

        name = g.first("applicant_name", "name", "full_name", "candidate_name")
        rec.add("full_name", name, method="ats_field_map")

        for email in _as_list(g.first("contact.email_address", "email", "emails", "contact.email")):
            rec.add("emails", email, method="ats_field_map")
        for phone in _as_list(g.first("contact.mobile", "contact.phone", "phone", "mobile", "phones")):
            rec.add("phones", phone, method="ats_field_map")

        rec.add("headline", g.first("headline", "job_title", "title", "current_title"),
                method="ats_field_map")
        rec.add("years_experience", g.first("experience_years", "years_experience", "yoe"),
                method="ats_field_map")

        location = g.first("location", "locale", "city", "current_location")
        if isinstance(location, dict):
            location = ", ".join(str(v) for v in
                                 [location.get("city"), location.get("region"), location.get("country")] if v)
        rec.add("location", location, method="ats_field_map")

        rec.add("links.linkedin", g.first("social.linkedin_url", "linkedin", "linkedin_url"),
                method="ats_field_map")
        rec.add("links.github", g.first("social.github_url", "github", "github_url"),
                method="ats_field_map")
        rec.add("links.portfolio", g.first("social.website", "website", "portfolio"),
                method="ats_field_map")

        for skill in _as_list(g.first("skill_tags", "skills", "competencies")):
            rec.add("skills", _skill_name(skill), method="ats_field_map")

        for job in _as_list(g.first("history", "work_history", "experience", "positions")):
            if isinstance(job, dict):
                rec.add("experience", {
                    "company": job.get("org") or job.get("company") or job.get("employer"),
                    "title": job.get("role") or job.get("title") or job.get("position"),
                    "start": job.get("from") or job.get("start") or job.get("start_date"),
                    "end": job.get("to") or job.get("end") or job.get("end_date"),
                    "summary": job.get("summary") or job.get("description"),
                }, method="ats_field_map")

        for sch in _as_list(g.first("schools", "education", "degrees")):
            if isinstance(sch, dict):
                rec.add("education", {
                    "institution": sch.get("name") or sch.get("institution") or sch.get("school"),
                    "degree": sch.get("degree") or sch.get("qualification"),
                    "field": sch.get("major") or sch.get("field") or sch.get("field_of_study"),
                    "end_year": sch.get("grad") or sch.get("end_year") or sch.get("graduation_year"),
                }, method="ats_field_map")

        rec.match_hints = {
            "emails": _as_list(g.first("contact.email_address", "email", "emails")),
            "name": name,
            "github": github_handle(g.first("social.github_url", "github", "github_url")),
            "linkedin": linkedin_handle(g.first("social.linkedin_url", "linkedin", "linkedin_url")),
        }
        return rec


class _Getter:
    """Reads dotted paths (a.b.c) from a nested dict, returning the first non-empty hit."""

    def __init__(self, data: dict):
        self._data = data

    def first(self, *paths: str) -> Any:
        for path in paths:
            val = self._dig(path)
            if val not in (None, "", [], {}):
                return val
        return None

    def _dig(self, path: str) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return None
        return node


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _skill_name(skill: Any) -> Any:
    if isinstance(skill, dict):
        return skill.get("name") or skill.get("skill") or skill.get("tag")
    return skill
