"""Tests for identity resolution + field/confidence merging — the heart of the engine."""
from transformer import merge
from transformer.claim_normalize import normalize_record
from transformer.models import SourceRecord


def _csv_record(source, name, email, phone=None, title=None):
    rec = SourceRecord(source=source)
    rec.add("full_name", name, "csv_column")
    if email:
        rec.add("emails", email, "csv_column")
    if phone:
        rec.add("phones", phone, "csv_column")
    if title:
        rec.add("headline", title, "csv_column")
    rec.match_hints = {"emails": [email] if email else [], "name": name}
    return normalize_record(rec)


def _merge(records):
    groups = merge.resolve_identities(records)
    return [merge.merge_group(g) for g in groups]


def test_same_email_merges_into_one_candidate():
    recs = [
        _csv_record("recruiter_csv:a", "Ada Lovelace", "ada@x.io", phone="(415) 555-0132"),
        _csv_record("ats_json:b", "Ada Lovelace", "ada@x.io", phone="+1 415 555 0132"),
    ]
    profiles = _merge(recs)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.full_name == "Ada Lovelace"
    assert p.emails == ["ada@x.io"]
    assert p.phones == ["+14155550132"]  # both normalize to the same E.164, deduped


def test_agreement_raises_confidence():
    """Two independent sources asserting the same name should beat a single source."""
    one = _merge([_csv_record("recruiter_csv:a", "Ada Lovelace", "ada@x.io")])[0]
    two = _merge([
        _csv_record("recruiter_csv:a", "Ada Lovelace", "ada@x.io"),
        _csv_record("ats_json:b", "Ada Lovelace", "ada@x.io"),
    ])[0]
    assert two.field_confidence["full_name"] > one.field_confidence["full_name"]


def test_conflict_resolution_prefers_trusted_source_and_penalizes():
    # Same person (shared email), conflicting names. ATS is trusted over notes for names.
    ats = SourceRecord(source="ats_json:b")
    ats.add("full_name", "Ada Lovelace", "ats_field_map")
    ats.add("emails", "ada@x.io", "ats_field_map")
    ats.match_hints = {"emails": ["ada@x.io"], "name": "Ada Lovelace"}

    notes = SourceRecord(source="recruiter_notes:c")
    notes.add("full_name", "Ada L", "regex_freetext")
    notes.add("emails", "ada@x.io", "regex_freetext")
    notes.match_hints = {"emails": ["ada@x.io"], "name": "Ada L"}

    p = _merge([normalize_record(ats), normalize_record(notes)])[0]
    assert p.full_name == "Ada Lovelace"          # trusted source wins
    # provenance points at the winning source
    name_prov = [pr for pr in p.provenance if pr["field"] == "full_name"]
    assert name_prov and name_prov[0]["source"] == "ats_json:b"


def test_handle_links_github_profile_without_email():
    """A GitHub profile (no email) must merge with an ATS record via the github handle."""
    ats = SourceRecord(source="ats_json:b")
    ats.add("full_name", "Ada Lovelace", "ats_field_map")
    ats.add("emails", "ada@x.io", "ats_field_map")
    ats.add("links.github", "https://github.com/ada-l", "ats_field_map")
    ats.match_hints = {"emails": ["ada@x.io"], "name": "Ada Lovelace",
                       "github": "ada-l", "linkedin": None}

    gh = SourceRecord(source="github:g")
    gh.add("skills", "Rust", "github_api")
    gh.add("links.github", "https://github.com/ada-l", "github_api")
    gh.match_hints = {"emails": [], "name": "Ada Lovelace", "github": "ada-l", "linkedin": None}

    profiles = _merge([normalize_record(ats), normalize_record(gh)])
    assert len(profiles) == 1
    assert any(s["name"] == "Rust" for s in profiles[0].skills)


def test_distinct_emails_same_name_do_not_merge():
    recs = [
        _csv_record("recruiter_csv:a", "John Smith", "john1@x.io"),
        _csv_record("recruiter_csv:a", "John Smith", "john2@y.io"),
    ]
    assert len(_merge(recs)) == 2


def test_skill_agreement_lists_multiple_sources():
    a = SourceRecord(source="ats_json:b")
    a.add("emails", "ada@x.io", "ats_field_map")
    a.add("skills", "python", "ats_field_map")
    a.match_hints = {"emails": ["ada@x.io"], "name": None}
    b = SourceRecord(source="github:g")
    b.add("emails", "ada@x.io", "github_api")
    b.add("skills", "Python", "github_api")
    b.match_hints = {"emails": ["ada@x.io"], "name": None}

    p = _merge([normalize_record(a), normalize_record(b)])[0]
    py = [s for s in p.skills if s["name"] == "Python"][0]
    assert set(py["sources"]) == {"ats_json", "github"}  # agreement recorded


def test_overall_confidence_bounded():
    p = _merge([_csv_record("recruiter_csv:a", "Ada Lovelace", "ada@x.io")])[0]
    assert 0.0 <= p.overall_confidence <= 0.99


def test_candidate_id_is_deterministic():
    a = _merge([_csv_record("recruiter_csv:a", "Ada Lovelace", "ada@x.io")])[0]
    b = _merge([_csv_record("recruiter_csv:a", "Ada Lovelace", "ada@x.io")])[0]
    assert a.candidate_id == b.candidate_id
