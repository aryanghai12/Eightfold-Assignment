"""Unit tests for the pure normalizers — the layer that must never invent data."""
import pytest

from transformer import normalize as nz


@pytest.mark.parametrize("raw,expected", [
    ("(415) 555-0132", "+14155550132"),
    ("+1-415-555-0132", "+14155550132"),
    ("+44 20 7946 0958", "+442079460958"),
    ("415.555.0132", "+14155550132"),
])
def test_phone_to_e164(raw, expected):
    assert nz.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["not-a-phone", "12", "", None, "555"])
def test_phone_garbage_is_dropped(raw):
    assert nz.normalize_phone(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("2019-03", "2019-03"),
    ("03/2019", "2019-03"),
    ("Mar 2019", "2019-03"),
    ("March 2019", "2019-03"),
    ("2019", "2019-01"),
    ("Present", "present"),
    ("current", "present"),
])
def test_date_normalization(raw, expected):
    assert nz.normalize_date(raw) == expected


@pytest.mark.parametrize("raw", ["someday", "13/2019", "", None])
def test_date_garbage_is_dropped(raw):
    assert nz.normalize_date(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("United Kingdom", "GB"), ("UK", "GB"), ("England", "GB"),
    ("USA", "US"), ("United States", "US"), ("India", "IN"), ("DE", "DE"),
])
def test_country_to_iso2(raw, expected):
    assert nz.normalize_country(raw) == expected


def test_country_unknown_is_none():
    assert nz.normalize_country("Atlantis") is None


def test_parse_location_city_region_country():
    assert nz.parse_location("San Francisco, CA, USA") == {
        "city": "San Francisco", "region": "CA", "country": "US"}


def test_parse_location_city_only_infers_country():
    loc = nz.parse_location("London")
    assert loc["city"] == "London" and loc["country"] == "GB"


@pytest.mark.parametrize("raw,expected", [
    ("  ada   lovelace ", "Ada Lovelace"),
    ("ALAN TURING", "Alan Turing"),
    ("grace hopper", "Grace Hopper"),
])
def test_name_normalization(raw, expected):
    assert nz.normalize_name(raw) == expected


def test_name_rejects_numbers():
    assert nz.normalize_name("Agent 47") is None


@pytest.mark.parametrize("raw,expected", [
    ("~12 yrs", 12), ("8+ years", 8), (6, 6), (5.5, 5.5), ("0", 0),
])
def test_years_experience(raw, expected):
    assert nz.normalize_years_experience(raw) == expected


@pytest.mark.parametrize("raw", ["lots", None, "999"])
def test_years_experience_garbage(raw):
    assert nz.normalize_years_experience(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("ADA@ANALYTICAL.IO", "ada@analytical.io"),
    ("  bob@x.co ", "bob@x.co"),
])
def test_email_normalization(raw, expected):
    assert nz.normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["not-an-email", "a@b", "", None])
def test_email_garbage_is_dropped(raw):
    assert nz.normalize_email(raw) is None
