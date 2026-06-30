"""Output validation: check the projected dict against the *requested* schema.

We deliberately hand-roll a tiny type checker instead of pulling in a JSON-Schema library:
it's a handful of types, the rules are easy to read and defend in review, and it keeps the
project dependency-light (one less thing to break on a fresh machine). Validation runs on
every output before it's returned — a value that doesn't match its declared type, or a missing
required field, is an error, not a silent pass.

Supported type names: string, number, integer, boolean, string[], number[], object,
object[], any.
"""
from __future__ import annotations

from typing import Any


class ValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


_SCALAR_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "any": lambda v: True,
}


def validate(output: dict[str, Any], config: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings ([] means valid). Does not raise."""
    errors: list[str] = []
    fields = config.get("fields") or []
    for spec in fields:
        key = spec["path"]
        declared = spec.get("type", "any")
        required = bool(spec.get("required"))
        present = key in output
        value = output.get(key)

        if not present:
            # Could have been intentionally omitted by on_missing='omit'; only an error if required.
            if required:
                errors.append(f"required field '{key}' is missing")
            continue

        if value is None:
            if required:
                errors.append(f"required field '{key}' is null")
            continue  # optional nulls are allowed (honestly empty)

        errors.extend(_check_type(key, value, declared))
    return errors


def validate_or_raise(output: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    errors = validate(output, config)
    if errors:
        raise ValidationError(errors)
    return output


def _check_type(key: str, value: Any, declared: str) -> list[str]:
    if declared.endswith("[]"):
        inner = declared[:-2]
        if not isinstance(value, list):
            return [f"field '{key}' should be {declared} but is {type(value).__name__}"]
        bad = [i for i, item in enumerate(value) if not _scalar_ok(inner, item)]
        if bad:
            return [f"field '{key}[{bad[0]}]' violates element type '{inner}'"]
        return []
    if not _scalar_ok(declared, value):
        return [f"field '{key}' should be {declared} but is {type(value).__name__}"]
    return []


def _scalar_ok(declared: str, value: Any) -> bool:
    check = _SCALAR_CHECKS.get(declared)
    if check is None:
        return True  # unknown declared type -> don't block (forward-compatible)
    return check(value)
