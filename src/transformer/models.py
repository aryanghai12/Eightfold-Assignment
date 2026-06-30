"""Core data structures for the candidate transformer.

There are two layers, kept deliberately separate:

* The **claim layer** (`Claim`, `SourceRecord`) is what extractors emit. A claim is
  one source's assertion about one canonical field, tagged with how it was obtained and
  how much we trust it on arrival. Extractors never merge or decide — they only observe.

* The **canonical layer** (`CanonicalProfile`) is the single, merged truth for one
  candidate. It is built by the merge engine and is the only thing the projection layer reads.

Keeping these apart is what makes the system explainable: every value in the canonical
profile can be traced back to the exact claims (and therefore sources) that produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from . import sourcerank


# Canonical field names. Centralised so the rest of the codebase never hard-codes strings.
SCALAR_FIELDS = ("full_name", "headline", "years_experience")
LIST_FIELDS = ("emails", "phones", "skills")
STRUCT_FIELDS = ("location", "links", "experience", "education")


@dataclass(frozen=True)
class Claim:
    """One source's assertion about one canonical field.

    Attributes:
        field: canonical field name the claim is about (e.g. "emails", "full_name").
        value: the *normalized* value (normalization happens before merge). For list
            fields this is a single element (one Claim per element).
        source: stable id of the source, e.g. "recruiter_csv:samples/recruiter_export.csv".
        method: how the value was obtained, e.g. "csv_column", "regex_email", "ats_field_map".
        base_confidence: 0..1 trust in this value *before* cross-source agreement is considered.
    """

    field: str
    value: Any
    source: str
    method: str
    base_confidence: float


@dataclass
class SourceRecord:
    """All claims one source makes about one candidate.

    A single source file can yield many SourceRecords (e.g. one CSV row per candidate).
    `match_hints` carries normalized identity signals (emails, name) used to group
    records that describe the same person across sources.
    """

    source: str
    claims: list[Claim] = field(default_factory=list)
    match_hints: dict[str, Any] = field(default_factory=dict)

    def add(self, fieldname: str, value: Any, method: str) -> None:
        """Append a raw claim, silently dropping None/empty values (we never invent data).

        Base confidence is derived centrally from the source-trust x method-certainty model
        (see sourcerank), so extractors never hand-pick confidence numbers. The trust table is
        keyed by the top-level field (e.g. "links" for "links.github").
        """
        if value is None or value == "" or value == []:
            return
        base_field = fieldname.split(".", 1)[0]
        conf = sourcerank.base_confidence(self.source, base_field, method)
        self.claims.append(
            Claim(field=fieldname, value=value, source=self.source,
                  method=method, base_confidence=conf)
        )


@dataclass
class CanonicalProfile:
    """The single merged profile for one candidate (the internal source of truth).

    This mirrors the default output schema, plus `field_confidence` which the projection
    layer reads when a config asks to include confidence. The projection layer treats this
    object (via `to_dict`) as a read-only document it resolves paths against.
    """

    candidate_id: str = ""
    full_name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    location: dict[str, Any] = field(default_factory=lambda: {"city": None, "region": None, "country": None})
    links: dict[str, Any] = field(default_factory=lambda: {"linkedin": None, "github": None, "portfolio": None, "other": []})
    headline: str | None = None
    years_experience: float | None = None
    skills: list[dict[str, Any]] = field(default_factory=list)        # [{name, confidence, sources[]}]
    experience: list[dict[str, Any]] = field(default_factory=list)    # [{company, title, start, end, summary}]
    education: list[dict[str, Any]] = field(default_factory=list)     # [{institution, degree, field, end_year}]
    provenance: list[dict[str, str]] = field(default_factory=list)    # [{field, source, method}]
    overall_confidence: float = 0.0
    field_confidence: dict[str, float] = field(default_factory=dict)  # internal aid for projection

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
