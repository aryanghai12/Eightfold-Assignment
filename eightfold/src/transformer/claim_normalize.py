"""Normalize stage: raw claims -> canonical-format claims.

Extractors emit raw values; this stage runs every claim through the right pure normalizer
(see normalize.py / skills.py) based on its field. A claim whose value can't be normalized is
**dropped** (honestly empty beats wrongly full). The source/method/confidence are preserved,
so provenance survives normalization. Skills are special-cased: the value becomes
`{"name", "canonical"}` so the merge stage can tell dictionary-matched skills from passthroughs.
"""
from __future__ import annotations

import re
from dataclasses import replace

from . import normalize as nz
from .models import Claim, SourceRecord
from .skills import canonicalize_skill


def normalize_record(rec: SourceRecord) -> SourceRecord:
    out = SourceRecord(source=rec.source, match_hints=_normalize_hints(rec.match_hints))
    for claim in rec.claims:
        new_value = _normalize_value(claim.field, claim.value)
        if new_value is None or new_value == "" or new_value == []:
            continue
        out.claims.append(replace(claim, value=new_value))
    return out


def _normalize_value(field: str, value):
    if field == "full_name":
        return nz.normalize_name(value)
    if field == "emails":
        return nz.normalize_email(value)
    if field == "phones":
        return nz.normalize_phone(value)
    if field == "skills":
        cs = canonicalize_skill(value)
        return {"name": cs.name, "canonical": cs.canonical} if cs else None
    if field == "headline":
        return _clean_text(value)
    if field == "years_experience":
        return nz.normalize_years_experience(value)
    if field == "location":
        loc = nz.parse_location(value) if isinstance(value, str) else value
        return loc if any(loc.get(k) for k in ("city", "region", "country")) else None
    if field.startswith("links."):
        return _normalize_url(field, value)
    if field == "experience":
        return _normalize_experience(value)
    if field == "education":
        return _normalize_education(value)
    return _clean_text(value) if isinstance(value, str) else value


def _normalize_hints(hints: dict) -> dict:
    emails = [e for e in (nz.normalize_email(x) for x in hints.get("emails", []) or []) if e]
    return {
        "emails": emails,
        "name": nz.normalize_name(hints.get("name")),
        "github": hints.get("github"),
        "linkedin": hints.get("linkedin"),
    }


def _clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    s = re.sub(r"\s+", " ", value.strip())
    return s or None


def _normalize_url(field: str, value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


_TITLE_FILLER = re.compile(r"^(currently|current|now|previously|formerly|present)\s+", re.IGNORECASE)


def _normalize_experience(job) -> dict | None:
    if not isinstance(job, dict):
        return None
    company = _clean_text(job.get("company"))
    title = _clean_text(job.get("title"))
    if title:  # drop leading filler so "Currently Principal Engineer" == "Principal Engineer"
        title = _TITLE_FILLER.sub("", title).strip() or None
    if not company and not title:
        return None
    return {
        "company": company,
        "title": title,
        "start": nz.normalize_date(job.get("start")),
        "end": nz.normalize_date(job.get("end")) or ("present" if job.get("end") is None else None),
        "summary": _clean_text(job.get("summary")),
    }


def _normalize_education(edu) -> dict | None:
    if not isinstance(edu, dict):
        return None
    institution = _clean_text(edu.get("institution"))
    degree = _clean_text(edu.get("degree"))
    if not institution and not degree:
        return None
    return {
        "institution": institution,
        "degree": degree,
        "field": _clean_text(edu.get("field")),
        "end_year": nz.end_year_of(str(edu.get("end_year")) if edu.get("end_year") is not None else None),
    }
