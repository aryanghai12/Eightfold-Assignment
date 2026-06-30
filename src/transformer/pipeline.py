"""Pipeline orchestration: detect -> extract -> normalize -> merge -> project -> validate.

This wires the stages together and is the single entry point used by both the CLI and the
tests. Two robustness guarantees live here:

* **No source can crash the run.** Every extractor call is wrapped; a failure becomes a
  warning and the pipeline carries on with the other sources.
* **Determinism.** Inputs are processed in a stable, sorted order and every downstream stage
  is order-independent, so the same inputs always yield byte-identical output.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any

from . import detect, merge
from .claim_normalize import normalize_record
from .extractors import build_registry
from .projection import ProjectionError, project
from .validation import validate


@dataclass
class CandidateResult:
    canonical: dict[str, Any]
    output: dict[str, Any] | None
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    candidates: list[CandidateResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(not c.validation_errors for c in self.candidates)


def run_pipeline(input_paths: list[str], config: dict[str, Any],
                 fetch_github: bool = False,
                 type_overrides: dict[str, str] | None = None) -> PipelineResult:
    type_overrides = type_overrides or {}
    registry = build_registry(fetch_github=fetch_github)
    result = PipelineResult()
    raw_records = []
    source_counts: dict[str, int] = {}

    # ---- detect + extract (guarded per source)
    for path in sorted(input_paths):
        stype = type_overrides.get(path) or detect.detect_source_type(path)
        if stype is None or stype not in registry:
            result.warnings.append(f"skipped (unrecognized source type): {path}")
            continue
        try:
            records = registry[stype].extract(path)
        except Exception as exc:  # never let one bad source kill the run
            result.warnings.append(f"extractor '{stype}' failed on {path}: {exc.__class__.__name__}: {exc}")
            if _debug():
                result.warnings.append(traceback.format_exc())
            continue
        if not records:
            result.warnings.append(f"no candidates extracted from {path} ({stype})")
        source_counts[stype] = source_counts.get(stype, 0) + len(records)
        raw_records.extend(records)

    # ---- normalize
    normalized = [normalize_record(r) for r in raw_records]

    # ---- merge (identity resolution + field resolution)
    groups = merge.resolve_identities(normalized)
    profiles = [merge.merge_group(g) for g in groups]
    # Stable output order: by candidate_id.
    profiles.sort(key=lambda p: p.candidate_id)

    # ---- project + validate
    for profile in profiles:
        canonical = profile.to_dict()
        try:
            output = project(canonical, config)
            errors = validate(output, config)
        except ProjectionError as exc:
            output, errors = None, [f"projection error: {exc}"]
        result.candidates.append(CandidateResult(canonical=canonical, output=output,
                                                  validation_errors=errors))

    result.stats = {
        "input_files": len(input_paths),
        "records_extracted": len(raw_records),
        "candidates": len(profiles),
        "by_source": source_counts,
        "all_valid": result.ok,
    }
    return result


def _debug() -> bool:
    import os
    return os.environ.get("TRANSFORMER_DEBUG") == "1"
