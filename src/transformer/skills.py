"""Skill canonicalization.

Different sources spell the same skill many ways: "JS", "Javascript", "node.js", "ReactJS".
We map known aliases to one canonical name so the same skill from two sources merges into one
entry (and its confidence rises because the sources agree). An unknown skill is *kept* but
title-cased — we don't want to silently drop a real skill just because it isn't in our table —
and it is flagged as `canonical=False` so callers know it was not dictionary-matched.

Deterministic and offline. The alias table is the single source of truth; extend it freely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# canonical name -> list of lower-case aliases (the canonical name itself is always matched)
_CANON: dict[str, list[str]] = {
    "Python": ["py"],
    "JavaScript": ["js", "java script", "ecmascript"],
    "TypeScript": ["ts"],
    "Java": [],
    "C++": ["cpp", "c plus plus"],
    "C": [],
    "C#": ["c sharp", "csharp", "dotnet c#"],
    "Go": ["golang"],
    "Rust": [],
    "Ruby": [],
    "PHP": [],
    "Scala": [],
    "Kotlin": [],
    "Swift": [],
    "R": [],
    "SQL": [],
    "React": ["react.js", "reactjs", "react js"],
    "Node.js": ["node", "nodejs", "node js"],
    "Angular": ["angular.js", "angularjs"],
    "Vue.js": ["vue", "vuejs"],
    "Django": [],
    "Flask": [],
    "Spring": ["spring boot", "springboot"],
    "Express": ["express.js", "expressjs"],
    "PostgreSQL": ["postgres", "postgresql", "psql"],
    "MySQL": [],
    "MongoDB": ["mongo"],
    "Redis": [],
    "Elasticsearch": ["elastic search", "es"],
    "Kafka": ["apache kafka"],
    "Docker": [],
    "Kubernetes": ["k8s", "kube"],
    "AWS": ["amazon web services"],
    "Google Cloud": ["gcp", "google cloud platform"],
    "Azure": ["microsoft azure"],
    "Terraform": [],
    "GraphQL": ["graph ql"],
    "REST APIs": ["rest", "restful", "rest api", "restful apis"],
    "Machine Learning": ["ml"],
    "Deep Learning": ["dl"],
    "NLP": ["natural language processing"],
    "TensorFlow": ["tensor flow"],
    "PyTorch": ["torch"],
    "Pandas": [],
    "NumPy": ["numpy"],
    "Distributed Systems": ["distributed computing", "distributed system"],
    "Microservices": ["micro services", "micro-services"],
    "CI/CD": ["cicd", "ci cd", "continuous integration"],
    "Git": [],
    "Linux": [],
}

# Build a reverse lookup: alias (lower) -> canonical. Built once at import.
_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in _CANON.items():
    _ALIAS_TO_CANON[_canon.lower()] = _canon
    for _a in _aliases:
        _ALIAS_TO_CANON[_a] = _canon


@dataclass(frozen=True)
class CanonSkill:
    name: str
    canonical: bool  # True if matched against the dictionary, False if passed through as-is


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().strip(".,;/")).strip()


def canonicalize_skill(raw: str | None) -> CanonSkill | None:
    """Map one raw skill string to its canonical form. None for empty/garbage input."""
    if not raw:
        return None
    cleaned = _clean(raw)
    if not cleaned or len(cleaned) > 40:
        return None
    hit = _ALIAS_TO_CANON.get(cleaned.lower())
    if hit:
        return CanonSkill(name=hit, canonical=True)
    # Keep unknown-but-plausible skills, title-cased, flagged as non-dictionary.
    pretty = cleaned if cleaned.isupper() else " ".join(w.capitalize() for w in cleaned.split())
    return CanonSkill(name=pretty, canonical=False)


def canonicalize_skill_name(raw: str | None) -> str | None:
    """Convenience: just the canonical name string (used by the projection `normalize` hook)."""
    cs = canonicalize_skill(raw)
    return cs.name if cs else None
