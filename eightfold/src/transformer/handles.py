"""Profile-handle extraction for identity resolution.

GitHub/LinkedIn handles are strong, unique identifiers — often the only thing that links a
GitHub profile (which usually hides the email) to the same person seen in an ATS or CSV. We
extract a normalized handle from any URL form so the merge stage can union records on it.
"""
from __future__ import annotations

import re

_GH = re.compile(r"github\.com/([A-Za-z0-9\-_]+)", re.IGNORECASE)
_LI = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", re.IGNORECASE)
_RESERVED = {"orgs", "about", "features", "settings", "marketplace", "sponsors"}


def github_handle(text: str | None) -> str | None:
    if not text:
        return None
    m = _GH.search(text)
    if not m:
        return None
    handle = m.group(1).lower()
    return handle if handle not in _RESERVED else None


def linkedin_handle(text: str | None) -> str | None:
    if not text:
        return None
    m = _LI.search(text)
    return m.group(1).lower() if m else None
