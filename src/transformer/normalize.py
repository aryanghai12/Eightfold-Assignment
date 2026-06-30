"""Normalizers: turn raw strings into canonical formats, or return None.

Golden rule for this whole file: **if a value cannot be confidently normalized, return
None.** A dropped value becomes `null` downstream and is honestly empty. We never guess a
format we are unsure about, because "wrong-but-confident" is the failure mode we most want
to avoid.

Every function here is pure and deterministic: same input -> same output, no clocks, no
network, no global state.
"""
from __future__ import annotations

import re
from datetime import date

try:  # phonenumbers is the one third-party lib; we degrade gracefully if it's absent.
    import phonenumbers
    _HAS_PHONENUMBERS = True
except Exception:  # pragma: no cover - exercised only in stripped environments
    _HAS_PHONENUMBERS = False


# --------------------------------------------------------------------------- emails
_EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


def normalize_email(raw: str | None) -> str | None:
    """Lower-case and trim an email; return None if it is not a syntactically valid address."""
    if not raw:
        return None
    candidate = raw.strip().strip("<>").lower()
    return candidate if _EMAIL_RE.match(candidate) else None


# --------------------------------------------------------------------------- phones
def normalize_phone(raw: str | None, default_region: str = "US") -> str | None:
    """Return an E.164 phone string (e.g. "+14155550132") or None.

    Uses Google's libphonenumber when available (correct, locale-aware). Falls back to a
    conservative heuristic that only accepts a clearly-shaped international/US number so we
    never emit a malformed E.164 string.
    """
    if not raw:
        return None
    raw = raw.strip()

    if _HAS_PHONENUMBERS:
        try:
            parsed = phonenumbers.parse(raw, None if raw.startswith("+") else default_region)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            return None
        return None

    # Fallback: strip formatting, keep a leading +, validate length conservatively.
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+") and 8 <= len(digits) - 1 <= 15:
        return digits
    bare = digits.lstrip("+")
    if len(bare) == 10 and default_region == "US":
        return "+1" + bare
    if len(bare) == 11 and bare.startswith("1") and default_region == "US":
        return "+" + bare
    return None


# --------------------------------------------------------------------------- dates
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_PRESENT = {"present", "current", "now", "ongoing", "today"}


def normalize_date(raw: str | None) -> str | None:
    """Normalize a date to "YYYY-MM", or "present" for an open-ended end date, or None.

    Accepts: "2019-03", "2019/3", "03/2019", "Mar 2019", "March 2019", "2019" (-> "2019-01"),
    "Present"/"Current". Anything else returns None rather than a guess.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if s in _PRESENT:
        return "present"

    # YYYY-MM or YYYY/MM
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})", s)
    if m:
        return _ym(int(m.group(1)), int(m.group(2)))

    # MM-YYYY or MM/YYYY
    m = re.fullmatch(r"(\d{1,2})[-/](\d{4})", s)
    if m:
        return _ym(int(m.group(2)), int(m.group(1)))

    # "Mar 2019" / "March 2019" / "Mar, 2019"
    m = re.fullmatch(r"([a-z]+)\.?,?\s+(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return _ym(int(m.group(2)), _MONTHS[m.group(1)])

    # "2019 Mar"
    m = re.fullmatch(r"(\d{4})\s+([a-z]+)\.?", s)
    if m and m.group(2) in _MONTHS:
        return _ym(int(m.group(1)), _MONTHS[m.group(2)])

    # Bare year
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return _ym(int(m.group(1)), 1)

    return None


def _ym(year: int, month: int) -> str | None:
    if not (1900 <= year <= date.today().year + 1):
        return None
    if not (1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}"


def end_year_of(raw: str | None) -> int | None:
    """Extract a 4-digit graduation/end year as an int, or None."""
    ym = normalize_date(raw)
    if ym and ym != "present":
        return int(ym.split("-")[0])
    if raw:
        m = re.search(r"(19|20)\d{2}", raw)
        if m:
            return int(m.group(0))
    return None


# --------------------------------------------------------------------------- country
# Minimal ISO-3166 alpha-2 map covering common spellings/aliases. Extend as needed; an
# unknown country resolves to None (honestly empty) rather than a wrong code.
_COUNTRY_TO_ISO2 = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.a.": "US",
    "u.s.": "US", "us": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "great britain": "GB", "britain": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB",
    "india": "IN", "bharat": "IN",
    "canada": "CA", "germany": "DE", "deutschland": "DE", "france": "FR", "spain": "ES",
    "italy": "IT", "netherlands": "NL", "the netherlands": "NL", "holland": "NL",
    "ireland": "IE", "australia": "AU", "new zealand": "NZ", "singapore": "SG",
    "japan": "JP", "china": "CN", "brazil": "BR", "mexico": "MX", "poland": "PL",
    "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI", "switzerland": "CH",
    "portugal": "PT", "austria": "AT", "belgium": "BE", "israel": "IL",
    "united arab emirates": "AE", "uae": "AE", "south africa": "ZA",
}
# A handful of well-known city -> country fallbacks for free-text where only a city is given.
_CITY_TO_ISO2 = {
    "london": "GB", "manchester": "GB", "san francisco": "US", "new york": "US",
    "seattle": "US", "boston": "US", "austin": "US", "bengaluru": "IN", "bangalore": "IN",
    "mumbai": "IN", "delhi": "IN", "toronto": "CA", "berlin": "DE", "munich": "DE",
    "paris": "FR", "amsterdam": "NL", "dublin": "IE", "sydney": "AU", "singapore": "SG",
    "tokyo": "JP", "tel aviv": "IL", "zurich": "CH",
}


def normalize_country(raw: str | None) -> str | None:
    """Return an ISO-3166 alpha-2 country code, or None if unrecognized."""
    if not raw:
        return None
    key = raw.strip().lower().rstrip(".")
    if len(key) == 2 and key.upper() in set(_COUNTRY_TO_ISO2.values()):
        return key.upper()
    return _COUNTRY_TO_ISO2.get(key)


def parse_location(raw: str | None) -> dict[str, str | None]:
    """Parse a free-form location like "London, UK" or "San Francisco, CA, USA".

    Returns {city, region, country(ISO-2)}. Any part we can't resolve stays None.
    """
    loc = {"city": None, "region": None, "country": None}
    if not raw:
        return loc
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return loc

    # Last part may be a country.
    country = normalize_country(parts[-1])
    if country:
        loc["country"] = country
        parts = parts[:-1]
    if parts:
        loc["city"] = _titlecase_place(parts[0])
        if len(parts) > 1:
            loc["region"] = parts[1].upper() if len(parts[1]) <= 3 else _titlecase_place(parts[1])
    # City-only free text: infer country from a known city.
    if loc["country"] is None and loc["city"]:
        loc["country"] = _CITY_TO_ISO2.get(loc["city"].lower())
    return loc


def _titlecase_place(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


# --------------------------------------------------------------------------- names
def normalize_name(raw: str | None) -> str | None:
    """Trim, collapse whitespace, and title-case a person's name. None if empty/non-name."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.strip())
    s = s.strip(".,")
    if not s or any(ch.isdigit() for ch in s):
        return None
    # Preserve common particles in lower case but capitalize the rest.
    particles = {"de", "van", "von", "der", "den", "del", "la", "di", "da"}
    out = []
    for word in s.split(" "):
        lw = word.lower()
        if lw in particles:
            out.append(lw)
        elif "-" in word:
            out.append("-".join(p.capitalize() for p in word.split("-")))
        else:
            out.append(word.capitalize())
    return " ".join(out)


def normalize_years_experience(raw: object) -> float | None:
    """Coerce a years-of-experience value to a float, or None.

    Accepts numbers and strings like "~12 yrs", "8+ years", "6". Rejects nonsense and
    out-of-range values (0..70).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        years = float(raw)
    else:
        m = re.search(r"\d+(\.\d+)?", str(raw))
        if not m:
            return None
        years = float(m.group(0))
    if not 0 <= years <= 70:
        return None
    return int(years) if years.is_integer() else years
