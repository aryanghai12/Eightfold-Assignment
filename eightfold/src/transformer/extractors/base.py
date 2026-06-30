"""Extractor base class and shared helpers.

An extractor's only job is to *observe* — read one source file and emit raw `SourceRecord`s
(one per candidate found). It assigns `method` tags but performs **no normalization and no
merging**; those are separate, independently-tested stages. This keeps each extractor small,
and means a buggy or malformed source can only ever produce fewer claims, never a crash that
takes down the whole run (the pipeline wraps every extractor in a guard).
"""
from __future__ import annotations

import abc

from ..models import SourceRecord


class Extractor(abc.ABC):
    #: short stable name, e.g. "recruiter_csv" — also used as the source-id prefix.
    source_type: str = "base"

    def source_id(self, path: str) -> str:
        # Normalize separators so provenance is identical across OSes (stable golden tests).
        return f"{self.source_type}:{path.replace(chr(92), '/')}"

    @abc.abstractmethod
    def extract(self, path: str) -> list[SourceRecord]:
        """Parse `path` and return raw SourceRecords (possibly empty). Must not raise on
        malformed input — return what could be parsed."""
        raise NotImplementedError
