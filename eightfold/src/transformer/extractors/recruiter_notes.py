"""Recruiter notes extractor (unstructured free text).

Free text is the lowest-trust source, so we extract conservatively with labelled-pattern
regexes and accept that we'll miss things. Each note file is treated as one candidate. We
pull contact details, an optional name, a headline ("... at Company"), skills after a "skills
in/strong in" cue, location, years of experience, and any profile links. Everything stays raw
for the normalize stage; anything we can't find is simply not claimed (never invented).
"""
from __future__ import annotations

import re

from ..handles import github_handle, linkedin_handle
from ..models import SourceRecord
from .base import Extractor

_EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+?\d[\d\-\.\s()]{7,}\d)")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+", re.IGNORECASE)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_]+", re.IGNORECASE)
_YEARS = re.compile(r"~?\s*(\d{1,2})\+?\s*(?:years|yrs|yoe)\b", re.IGNORECASE)
# "Principal Engineer at Analytical Engines" / "Staff SWE @ Acme"
_TITLE_AT = re.compile(r"\b([A-Z][A-Za-z+/ ]{2,40}?)\s+(?:at|@)\s+([A-Z][A-Za-z0-9&.\- ]{1,40})")
# "strong in X, Y and Z" / "skills: X, Y, Z"
_SKILLS_CUE = re.compile(
    r"(?:strong in|skills?(?:\s*[:\-])|experienced in|proficient in|expertise in)\s+(.+?)(?:[.\n]|$)",
    re.IGNORECASE)
_LOCATION_CUE = re.compile(
    r"(?:based in|located in|lives in|location[:\-]?)\s+([A-Z][A-Za-z\- ]+(?:,\s*[A-Za-z\- ]+){0,2})",
    re.IGNORECASE)
# "Spoke with Ada Lovelace" / "Call with John Smith"
_NAME_CUE = re.compile(
    r"(?:spoke (?:with|to)|call(?:ed)? with|met with|candidate[:\-]?|re[:\-]?|chatted with)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})")


class RecruiterNotesExtractor(Extractor):
    source_type = "recruiter_notes"

    def extract(self, path: str) -> list[SourceRecord]:
        src = self.source_id(path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return []
        if not text.strip():
            return []

        rec = SourceRecord(source=src)

        emails = _dedup(m.group(0) for m in _EMAIL.finditer(text))
        for e in emails:
            rec.add("emails", e, method="regex_email")
        for p in _candidate_phones(text):
            rec.add("phones", p, method="regex_phone")

        name = self._guess_name(text)
        rec.add("full_name", name, method="regex_freetext")

        m = _TITLE_AT.search(text)
        if m:
            rec.add("headline", f"{m.group(1).strip()} at {m.group(2).strip()}", method="regex_freetext")
            rec.add("experience", {"company": m.group(2).strip(), "title": m.group(1).strip(),
                                   "start": None, "end": "present", "summary": None},
                    method="regex_freetext")

        m = _YEARS.search(text)
        if m:
            rec.add("years_experience", m.group(1), method="regex_freetext")

        m = _SKILLS_CUE.search(text)
        if m:
            for skill in _split_skills(m.group(1)):
                rec.add("skills", skill, method="regex_freetext")

        m = _LOCATION_CUE.search(text)
        if m:
            rec.add("location", m.group(1).strip(), method="regex_freetext")

        li = _LINKEDIN.search(text)
        if li:
            rec.add("links.linkedin", li.group(0), method="regex_freetext")
        gh = _GITHUB.search(text)
        if gh:
            rec.add("links.github", gh.group(0), method="regex_freetext")

        rec.match_hints = {
            "emails": emails, "name": name,
            "github": github_handle(gh.group(0)) if gh else None,
            "linkedin": linkedin_handle(li.group(0)) if li else None,
        }
        return [rec] if rec.claims else []

    @staticmethod
    def _guess_name(text: str) -> str | None:
        m = _NAME_CUE.search(text)
        if m:
            return m.group(1)
        # Fallback: a two/three-word Capitalized sequence in the first line.
        first_line = text.strip().splitlines()[0] if text.strip().splitlines() else ""
        m = re.match(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", first_line.strip())
        return m.group(1) if m else None


def _candidate_phones(text: str) -> list[str]:
    out = []
    for m in _PHONE.finditer(text):
        token = m.group(0).strip()
        digits = re.sub(r"\D", "", token)
        if 7 <= len(digits) <= 15:  # reject years, ids, etc.
            out.append(token)
    return _dedup(out)


def _split_skills(blob: str) -> list[str]:
    blob = re.sub(r"\band\b", ",", blob, flags=re.IGNORECASE)
    return [s.strip() for s in blob.split(",") if s.strip()]


def _dedup(items) -> list[str]:
    seen, out = set(), []
    for it in items:
        key = it.lower()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
