"""Source-type detection.

Given a file, decide which extractor should handle it. We prefer *content* sniffing over
file extensions (a `.txt` could be recruiter notes, a resume, or a list of GitHub URLs), but
fall back to the extension and allow an explicit per-file override (`path=source_type`).

Returns one of: recruiter_csv | ats_json | github | resume | recruiter_notes | None
(None = unrecognized; the pipeline skips it without crashing).
"""
from __future__ import annotations

import json
import os
import re

KNOWN_TYPES = ("recruiter_csv", "ats_json", "github", "resume", "recruiter_notes")

_GITHUB_URL_RE = re.compile(r"https?://(www\.)?github\.com/", re.IGNORECASE)
_RESUME_HEADERS = ("experience", "work experience", "education", "skills",
                   "employment", "professional summary", "projects")


def detect_source_type(path: str, sniff_bytes: int = 8192) -> str | None:
    ext = os.path.splitext(path)[1].lower()

    # Binary resume formats are unambiguous by extension.
    if ext in (".pdf", ".docx"):
        return "resume"
    if ext == ".csv":
        return "recruiter_csv"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(sniff_bytes)
    except OSError:
        return None

    if ext == ".json":
        return _classify_json(head)

    if ext in (".txt", ".md", ""):
        return _classify_text(head)

    # Unknown extension: try to sniff anyway.
    stripped = head.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _classify_json(head)
    return _classify_text(head)


def _classify_json(head: str) -> str | None:
    try:
        data = json.loads(head)
    except json.JSONDecodeError:
        # Truncated sniff buffer — fall back to keyword signals.
        if '"login"' in head and '"public_repos"' in head:
            return "github"
        return "ats_json"
    sample = data[0] if isinstance(data, list) and data else data
    if isinstance(sample, dict):
        keys = {k.lower() for k in sample.keys()}
        if {"login", "public_repos"} & keys or "html_url" in keys and "followers" in keys:
            return "github"
    return "ats_json"


def _classify_text(head: str) -> str | None:
    if not head.strip():
        return "recruiter_notes"  # empty/whitespace -> treat as (empty) notes, never crash

    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
    if lines:
        github_lines = sum(1 for ln in lines if _GITHUB_URL_RE.search(ln))
        if github_lines >= max(1, len(lines) // 2):
            return "github"

    low = head.lower()
    header_hits = sum(1 for h in _RESUME_HEADERS if re.search(rf"(?m)^\s*{re.escape(h)}\b", low))
    if header_hits >= 2:
        return "resume"
    return "recruiter_notes"
