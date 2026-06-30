"""Tests for the hand-rolled output validator."""
import pytest

from transformer.validation import validate, validate_or_raise, ValidationError


def test_valid_output_passes():
    cfg = {"fields": [{"path": "name", "type": "string", "required": True},
                      {"path": "emails", "type": "string[]"}]}
    assert validate({"name": "Ada", "emails": ["a@x.io"]}, cfg) == []


def test_required_missing_is_error():
    cfg = {"fields": [{"path": "name", "type": "string", "required": True}]}
    errs = validate({}, cfg)
    assert errs and "missing" in errs[0]


def test_required_null_is_error():
    cfg = {"fields": [{"path": "name", "type": "string", "required": True}]}
    errs = validate({"name": None}, cfg)
    assert errs and "null" in errs[0]


def test_optional_null_allowed():
    cfg = {"fields": [{"path": "headline", "type": "string"}]}
    assert validate({"headline": None}, cfg) == []


def test_wrong_scalar_type_is_error():
    cfg = {"fields": [{"path": "years", "type": "number"}]}
    errs = validate({"years": "twelve"}, cfg)
    assert errs and "should be number" in errs[0]


def test_wrong_list_element_type_is_error():
    cfg = {"fields": [{"path": "emails", "type": "string[]"}]}
    errs = validate({"emails": ["ok", 123]}, cfg)
    assert errs and "[1]" in errs[0]


def test_number_excludes_bool():
    cfg = {"fields": [{"path": "n", "type": "number"}]}
    assert validate({"n": True}, cfg)  # bool must not count as a number


def test_validate_or_raise():
    cfg = {"fields": [{"path": "name", "type": "string", "required": True}]}
    with pytest.raises(ValidationError):
        validate_or_raise({}, cfg)
