"""GitHub extractor (unstructured source backed by a public API).

Input is a file containing one or more GitHub profile URLs (one per line). For each user we
need their public profile (name, bio, blog, location, company) plus their top repo languages
as skill signals.

**Determinism is a hard requirement**, and a live API is neither deterministic nor always
reachable. So by default we read a *cached* API response from `samples/github_cache/<user>.json`
and only hit the network when explicitly asked (`fetch=True`). A missing cache entry in offline
mode is skipped gracefully — never a crash, never invented data. Cached fixtures make the demo
and the test suite reproducible offline.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from ..models import SourceRecord
from .base import Extractor

_GH_USER = re.compile(r"github\.com/([A-Za-z0-9\-_]+)", re.IGNORECASE)
_CACHE_DIRNAME = "github_cache"


class GitHubExtractor(Extractor):
    source_type = "github"

    def __init__(self, fetch: bool = False, cache_dir: str | None = None, timeout: float = 6.0):
        self.fetch = fetch
        self.cache_dir = cache_dir
        self.timeout = timeout

    def extract(self, path: str) -> list[SourceRecord]:
        usernames = self._read_usernames(path)
        cache_dir = self.cache_dir or os.path.join(os.path.dirname(os.path.abspath(path)), _CACHE_DIRNAME)
        records = []
        for user in usernames:
            payload = self._load_profile(user, cache_dir)
            if not payload:
                continue
            rec = self._map_profile(payload, self.source_id(path))
            if rec.claims:
                records.append(rec)
        return records

    def _read_usernames(self, path: str) -> list[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return []
        users, seen = [], set()
        for m in _GH_USER.finditer(text):
            u = m.group(1)
            if u.lower() not in seen and u.lower() not in ("orgs", "about", "features"):
                seen.add(u.lower())
                users.append(u)
        return users

    def _load_profile(self, user: str, cache_dir: str) -> dict | None:
        cache_path = os.path.join(cache_dir, f"{user}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                return None
        if not self.fetch:
            return None  # offline + no cache: skip gracefully
        return self._fetch_live(user)

    def _fetch_live(self, user: str) -> dict | None:  # pragma: no cover - network path
        try:
            profile = _get_json(f"https://api.github.com/users/{user}", self.timeout)
            repos = _get_json(f"https://api.github.com/users/{user}/repos?per_page=100&sort=pushed",
                              self.timeout) or []
            languages = []
            for repo in repos[:30]:
                lang = repo.get("language")
                if lang and lang not in languages:
                    languages.append(lang)
            profile["_languages"] = languages
            return profile
        except Exception:
            return None

    def _map_profile(self, p: dict, src: str) -> SourceRecord:
        rec = SourceRecord(source=src)
        rec.add("full_name", p.get("name"), method="github_api")
        rec.add("headline", p.get("bio"), method="github_api")
        rec.add("location", p.get("location"), method="github_api")
        rec.add("emails", p.get("email"), method="github_api")

        login = p.get("login")
        if login:
            rec.add("links.github", f"https://github.com/{login}", method="github_api")
        blog = (p.get("blog") or "").strip()
        if blog:
            rec.add("links.portfolio", blog if blog.startswith("http") else f"https://{blog}",
                    method="github_api")

        for lang in p.get("_languages", []) or []:
            rec.add("skills", lang, method="github_api")

        company = (p.get("company") or "").lstrip("@").strip()
        if company:
            rec.add("experience", {"company": company, "title": None,
                                   "start": None, "end": "present", "summary": None},
                    method="github_api")

        rec.match_hints = {
            "emails": [p["email"]] if p.get("email") else [],
            "name": p.get("name"),
            "github": login.lower() if login else None,
            "linkedin": None,
        }
        return rec


def _get_json(url: str, timeout: float):  # pragma: no cover - network path
    req = urllib.request.Request(url, headers={"User-Agent": "candidate-transformer",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
