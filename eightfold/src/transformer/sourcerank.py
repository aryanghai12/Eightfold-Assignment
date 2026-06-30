"""Source reliability model.

Confidence has to come from *somewhere* principled. We model it as two independent signals
that get multiplied:

1. **Source trust for a field** — how much we trust a given source *type* about a given
   *field*. A recruiter CSV is authoritative for contact details (a human typed them on
   purpose) but says nothing reliable about skills; a resume is great for skills and history
   but its self-reported "years of experience" is softer; free-text notes are weak everywhere.

2. **Method certainty** — how the value was pulled. A typed CSV column is near-certain;
   a regex over free text is shakier.

`base_confidence = source_trust(field) * method_certainty`. The merge engine then layers
cross-source *agreement* on top (see merge.py). All weights live here so the policy is one
readable table you can defend in review, not magic numbers sprinkled through the code.
"""
from __future__ import annotations

# Per-source-type, per-field trust in [0,1]. "_default" applies to fields not listed.
_SOURCE_TRUST: dict[str, dict[str, float]] = {
    "recruiter_csv": {
        "_default": 0.80,
        "full_name": 0.85, "emails": 0.90, "phones": 0.90,
        "experience": 0.75, "headline": 0.75, "skills": 0.30,
    },
    "ats_json": {
        "_default": 0.85,
        "full_name": 0.88, "emails": 0.92, "phones": 0.88,
        "skills": 0.80, "experience": 0.85, "education": 0.85,
        "years_experience": 0.80, "location": 0.80, "links": 0.85, "headline": 0.80,
    },
    "github": {
        "_default": 0.55,
        "full_name": 0.60, "links": 0.95, "skills": 0.70,
        "headline": 0.60, "location": 0.55, "emails": 0.70,
    },
    "resume": {
        "_default": 0.65,
        "full_name": 0.70, "emails": 0.80, "phones": 0.75,
        "skills": 0.78, "experience": 0.80, "education": 0.82,
        "headline": 0.65, "years_experience": 0.55, "location": 0.60, "links": 0.70,
    },
    "recruiter_notes": {
        "_default": 0.35,
        "full_name": 0.45, "emails": 0.55, "phones": 0.55,
        "skills": 0.40, "headline": 0.40, "location": 0.40, "years_experience": 0.35,
    },
}

# How much we trust an extraction *method*, independent of source.
_METHOD_CERTAINTY: dict[str, float] = {
    "csv_column": 0.98,
    "ats_field_map": 0.97,
    "json_field": 0.95,
    "github_api": 0.95,
    "resume_section": 0.85,
    "resume_regex": 0.78,
    "regex_email": 0.92,
    "regex_phone": 0.88,
    "regex_freetext": 0.62,
    "heuristic": 0.55,
}

# Tie-breaker ordering when two sources are otherwise equal (higher = wins ties).
_SOURCE_PRIORITY = ["ats_json", "recruiter_csv", "resume", "github", "recruiter_notes"]


def source_type_of(source_id: str) -> str:
    """Extract the source *type* from a source id like "recruiter_csv:path/to/file.csv"."""
    return source_id.split(":", 1)[0]


def source_trust(source_id: str, field: str) -> float:
    table = _SOURCE_TRUST.get(source_type_of(source_id), {"_default": 0.5})
    return table.get(field, table.get("_default", 0.5))


def method_certainty(method: str) -> float:
    return _METHOD_CERTAINTY.get(method, 0.6)


def base_confidence(source_id: str, field: str, method: str) -> float:
    return round(source_trust(source_id, field) * method_certainty(method), 4)


def source_priority(source_id: str) -> int:
    """Lower index in the priority list => higher priority. Returns a sortable rank."""
    stype = source_type_of(source_id)
    return _SOURCE_PRIORITY.index(stype) if stype in _SOURCE_PRIORITY else len(_SOURCE_PRIORITY)
