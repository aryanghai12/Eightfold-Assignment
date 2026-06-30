"""End-to-end pipeline tests: golden comparison, robustness, determinism."""
import json
import os

import pytest

from transformer.pipeline import run_pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "default_profiles.json")

# Relative paths (resolved against ROOT via the autouse chdir fixture below) so that the
# source ids baked into provenance are portable — the committed golden has no machine paths.
# Excludes the deliberately-malformed file used by the robustness test.
REAL_INPUTS = [
    "samples/recruiter_export.csv",
    "samples/ats_dump.json",
    "samples/notes/ada_notes.txt",
    "samples/resumes/alan_turing.txt",
    "samples/github_urls.txt",
]

DEFAULT_CONFIG = json.load(open(os.path.join(ROOT, "configs", "default.json"), encoding="utf-8"))


@pytest.fixture(autouse=True)
def _chdir_root(monkeypatch):
    """Run every test from the project root so relative sample paths resolve consistently."""
    monkeypatch.chdir(ROOT)


def _run(inputs, config=DEFAULT_CONFIG):
    return run_pipeline(inputs, config)


def test_end_to_end_matches_golden():
    result = _run(REAL_INPUTS)
    produced = [c.output for c in result.candidates]
    expected = json.load(open(GOLDEN, encoding="utf-8"))
    assert produced == expected


def test_every_candidate_is_schema_valid():
    result = _run(REAL_INPUTS)
    for c in result.candidates:
        assert c.validation_errors == [], c.validation_errors
    assert result.ok


def test_four_candidates_merged():
    result = _run(REAL_INPUTS)
    names = sorted(c.canonical["full_name"] for c in result.candidates)
    assert names == ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]


def test_ada_merged_across_all_four_sources():
    result = _run(REAL_INPUTS)
    ada = next(c.canonical for c in result.candidates if c.canonical["full_name"] == "Ada Lovelace")
    sources = {p["source"].split(":")[0] for p in ada["provenance"]}
    # Ada appears in CSV, ATS, notes and GitHub — all four should show up in provenance.
    assert {"recruiter_csv", "ats_json", "recruiter_notes", "github"} <= sources


def test_malformed_source_does_not_crash_and_is_warned():
    inputs = REAL_INPUTS + ["samples/malformed/broken_ats.json"]
    result = _run(inputs)
    assert result.ok                                   # good candidates still produced
    assert len(result.candidates) == 4
    assert any("broken_ats" in w for w in result.warnings)


def test_invalid_phone_is_dropped_not_invented():
    result = _run(REAL_INPUTS)
    kj = next(c for c in result.candidates if c.canonical["full_name"] == "Katherine Johnson")
    assert not kj.canonical["phones"]   # internal: empty list (no valid phone survived)
    assert kj.output["phones"] is None  # projected default: honestly null, never guessed


def test_run_is_deterministic():
    a = json.dumps([c.output for c in _run(REAL_INPUTS).candidates], sort_keys=True)
    b = json.dumps([c.output for c in _run(list(reversed(REAL_INPUTS))).candidates], sort_keys=True)
    assert a == b  # output is independent of input order


def test_empty_input_list_yields_no_candidates():
    result = run_pipeline([], DEFAULT_CONFIG)
    assert result.candidates == [] and result.ok
