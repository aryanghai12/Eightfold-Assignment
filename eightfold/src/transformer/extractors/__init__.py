"""Extractor registry: maps a detected source type to its extractor instance."""
from __future__ import annotations

from .ats_json import ATSJSONExtractor
from .base import Extractor
from .github import GitHubExtractor
from .recruiter_csv import RecruiterCSVExtractor
from .recruiter_notes import RecruiterNotesExtractor
from .resume import ResumeExtractor


def build_registry(fetch_github: bool = False) -> dict[str, Extractor]:
    """Return {source_type: Extractor}. `fetch_github` enables live GitHub API calls."""
    return {
        "recruiter_csv": RecruiterCSVExtractor(),
        "ats_json": ATSJSONExtractor(),
        "recruiter_notes": RecruiterNotesExtractor(),
        "resume": ResumeExtractor(),
        "github": GitHubExtractor(fetch=fetch_github),
    }


__all__ = ["build_registry", "Extractor"]
