"""Projection layer: canonical profile -> caller-requested output shape.

This is the "configurable output" twist. The engine above always produces the same rich
canonical record; this layer reshapes it per a runtime config — *no code changes*. A config
can select a subset of fields, rename them, pull from a canonical path (the `from` key),
apply a per-field normalization, toggle confidence/provenance, and decide what a missing value
becomes (null / omit / error).

The only thing this layer reads is the canonical dict, via a small, safe path mini-language:

    full_name            -> a scalar
    emails[0]            -> first list element
    location.city        -> nested field
    skills[].name        -> map a field over a list  -> list

Keeping projection separate from the engine is what lets us validate the output against the
*requested* schema (see validation.py) rather than a fixed one.
"""
from __future__ import annotations

import re
from typing import Any

from . import normalize as nz
from .skills import canonicalize_skill_name

_MISSING = object()  # sentinel distinct from a legitimately-present None


class ProjectionError(ValueError):
    """Raised when on_missing='error' and a required/any value is absent."""


def project(canonical: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Apply `config` to a canonical profile dict and return the projected output dict."""
    fields = config.get("fields") or _default_fields()
    on_missing = config.get("on_missing", "null")
    out: dict[str, Any] = {}
    field_conf_out: dict[str, float] = {}
    errors: list[str] = []
    included_base_fields: set[str] = set()

    for spec in fields:
        out_key = spec["path"]
        src_path = spec.get("from", spec["path"])
        raw = _resolve_path(canonical, src_path)

        if raw is _MISSING or raw is None or raw == [] or raw == "":
            if spec.get("required") and on_missing != "error":
                # Required + missing: emit null and let the validator flag it (single source of
                # truth for required-ness), unless the config wants a hard error.
                out[out_key] = None
            elif on_missing == "omit":
                continue
            elif on_missing == "error":
                errors.append(f"missing value for '{out_key}' (from '{src_path}')")
                continue
            else:  # "null"
                out[out_key] = None
            included_base_fields.add(_base_field(src_path))
            continue

        value = _apply_normalize(raw, spec.get("normalize"))
        out[out_key] = value
        included_base_fields.add(_base_field(src_path))

        base = _base_field(src_path)
        if base in canonical.get("field_confidence", {}):
            field_conf_out[out_key] = canonical["field_confidence"][base]

    if errors:
        raise ProjectionError("; ".join(errors))

    if config.get("include_confidence"):
        out["overall_confidence"] = canonical.get("overall_confidence", 0.0)
        out["field_confidence"] = field_conf_out
    if config.get("include_provenance"):
        out["provenance"] = [p for p in canonical.get("provenance", [])
                             if p.get("field") in included_base_fields]
    return out


# ----------------------------------------------------------------- path resolver
_TOKEN_RE = re.compile(r"([A-Za-z_][\w]*)(\[(\d+|)\])?")


def _resolve_path(root: Any, path: str) -> Any:
    """Resolve a path string against a nested dict/list. Returns _MISSING if any hop is absent."""
    node: Any = root
    for seg in path.split("."):
        m = _TOKEN_RE.fullmatch(seg)
        if not m:
            return _MISSING
        key, has_index, index = m.group(1), m.group(2), m.group(3)

        if isinstance(node, list):  # mapping a field over the list we're already on
            node = [item.get(key) if isinstance(item, dict) else None for item in node]
            node = [v for v in node if v is not None]
        elif isinstance(node, dict):
            if key not in node:
                return _MISSING
            node = node[key]
        else:
            return _MISSING

        if has_index:
            if index == "":          # "[]" => keep the list as-is (used as skills[].name)
                if not isinstance(node, list):
                    return _MISSING
            else:                    # "[n]" => index into the list
                i = int(index)
                if not isinstance(node, list) or i >= len(node):
                    return _MISSING
                node = node[i]
    return node


def _apply_normalize(value: Any, kind: str | None) -> Any:
    """Re-apply a normalization on the projected value. Idempotent for already-canonical data;
    its real job is to honour an explicit per-field request in the config."""
    if not kind:
        return value
    fn = {
        "E164": lambda v: nz.normalize_phone(v),
        "canonical": lambda v: canonicalize_skill_name(v),
        "lower": lambda v: v.lower() if isinstance(v, str) else v,
        "upper": lambda v: v.upper() if isinstance(v, str) else v,
        "title": lambda v: v.title() if isinstance(v, str) else v,
    }.get(kind)
    if not fn:
        return value
    if isinstance(value, list):
        return [fn(v) for v in value if fn(v) is not None]
    return fn(value)


def _base_field(path: str) -> str:
    return re.split(r"[.\[]", path, maxsplit=1)[0]


def _default_fields() -> list[dict]:
    """The default schema as a projection config (used when none is supplied)."""
    return [
        {"path": "candidate_id", "type": "string", "required": True},
        {"path": "full_name", "type": "string"},
        {"path": "emails", "type": "string[]"},
        {"path": "phones", "type": "string[]"},
        {"path": "location", "type": "object"},
        {"path": "links", "type": "object"},
        {"path": "headline", "type": "string"},
        {"path": "years_experience", "type": "number"},
        {"path": "skills", "type": "object[]"},
        {"path": "experience", "type": "object[]"},
        {"path": "education", "type": "object[]"},
    ]
