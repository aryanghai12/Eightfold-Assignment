"""Tests for the projection layer: path mini-language, remaps, normalize, on_missing."""
import pytest

from transformer.projection import project, _resolve_path, ProjectionError, _MISSING

CANON = {
    "candidate_id": "cand_1",
    "full_name": "Ada Lovelace",
    "emails": ["ada@x.io", "ada@home.io"],
    "phones": ["+14155550132"],
    "location": {"city": "London", "region": None, "country": "GB"},
    "links": {"linkedin": None, "github": "https://github.com/ada-l", "portfolio": None, "other": []},
    "skills": [{"name": "Python", "confidence": 0.9, "sources": ["ats_json"]},
               {"name": "Rust", "confidence": 0.8, "sources": ["github"]}],
    "headline": "Principal Engineer",
    "years_experience": 12,
    "overall_confidence": 0.91,
    "field_confidence": {"full_name": 0.95, "emails": 0.99, "skills": 0.9},
    "provenance": [{"field": "full_name", "source": "ats_json:x", "method": "ats_field_map"},
                   {"field": "skills", "source": "github:y", "method": "github_api"}],
}


@pytest.mark.parametrize("path,expected", [
    ("full_name", "Ada Lovelace"),
    ("emails[0]", "ada@x.io"),
    ("location.city", "London"),
    ("links.github", "https://github.com/ada-l"),
    ("skills[].name", ["Python", "Rust"]),
])
def test_path_resolver(path, expected):
    assert _resolve_path(CANON, path) == expected


def test_path_missing_returns_sentinel():
    assert _resolve_path(CANON, "emails[9]") is _MISSING
    assert _resolve_path(CANON, "nope.nope") is _MISSING


def test_remap_and_rename():
    cfg = {"fields": [
        {"path": "name", "from": "full_name", "type": "string"},
        {"path": "primary_email", "from": "emails[0]", "type": "string"},
    ]}
    out = project(CANON, cfg)
    assert out == {"name": "Ada Lovelace", "primary_email": "ada@x.io"}


def test_skills_canonical_projection_returns_string_list():
    cfg = {"fields": [{"path": "skills", "from": "skills[].name", "type": "string[]",
                       "normalize": "canonical"}]}
    out = project(CANON, cfg)
    assert out["skills"] == ["Python", "Rust"]


def test_on_missing_null():
    cfg = {"fields": [{"path": "headline2", "from": "headline_missing", "type": "string"}],
           "on_missing": "null"}
    assert project(CANON, cfg) == {"headline2": None}


def test_on_missing_omit():
    cfg = {"fields": [{"path": "name", "from": "full_name"},
                      {"path": "x", "from": "missing_field"}],
           "on_missing": "omit"}
    out = project(CANON, cfg)
    assert "x" not in out and out["name"] == "Ada Lovelace"


def test_on_missing_error():
    cfg = {"fields": [{"path": "x", "from": "missing_field"}], "on_missing": "error"}
    with pytest.raises(ProjectionError):
        project(CANON, cfg)


def test_include_confidence_and_provenance_flags():
    cfg = {"fields": [{"path": "full_name", "type": "string"}],
           "include_confidence": True, "include_provenance": True}
    out = project(CANON, cfg)
    assert out["overall_confidence"] == 0.91
    assert out["field_confidence"]["full_name"] == 0.95
    # provenance is filtered to included base fields only
    assert all(p["field"] == "full_name" for p in out["provenance"])


def test_phone_normalize_hook_idempotent():
    cfg = {"fields": [{"path": "phone", "from": "phones[0]", "normalize": "E164"}]}
    assert project(CANON, cfg)["phone"] == "+14155550132"
