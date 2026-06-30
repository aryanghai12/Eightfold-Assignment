"""Merge stage: many SourceRecords -> one CanonicalProfile per real person.

Two parts:

1. **Identity resolution** — group records that describe the same candidate. Primary key is a
   shared normalized email (strong signal). Records with no email fall back to an exact
   normalized-name match. Grouping is a deterministic union-find, so output never depends on
   input order.

2. **Field resolution + confidence** — for each canonical field, gather every claim from the
   group and pick a winner (scalars), a deduped union (lists), or a field-wise best (structs).
   Confidence = the best single claim's base confidence, *raised* when independent sources
   agree and *lowered* when they conflict. Every winning value contributes a provenance entry
   so the result stays fully traceable.

Design choice: confidence is bounded to [0, 0.99] — we never claim absolute certainty, which
keeps "wrong-but-confident" structurally impossible.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from . import sourcerank
from .models import Claim, CanonicalProfile, SourceRecord

AGREEMENT_BONUS = 0.05   # added per *extra* independent source that agrees
CONFLICT_MARGIN = 0.08   # runner-up within this score of the winner counts as a conflict
CONFLICT_PENALTY = 0.15  # multiplicative penalty applied to a conflicted winner
CONF_CAP = 0.99

# Weights for the overall_confidence rollup (identity fields matter most).
_OVERALL_WEIGHTS = {
    "full_name": 3.0, "emails": 3.0, "phones": 1.5, "headline": 1.0,
    "skills": 1.5, "experience": 1.5, "education": 1.0, "location": 1.0,
    "years_experience": 0.5, "links": 0.5,
}


# ============================================================ identity resolution
class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)  # bias to lower index => deterministic


def resolve_identities(records: list[SourceRecord]) -> list[list[SourceRecord]]:
    """Cluster records that refer to the same person. Returns groups in stable order."""
    uf = _UnionFind(len(records))
    by_email: dict[str, int] = {}
    by_handle: dict[str, int] = {}  # github:/linkedin: handles are strong unique identifiers
    by_name: dict[str, int] = {}

    for i, rec in enumerate(records):
        hints = rec.match_hints
        has_strong = bool(hints.get("emails")) or bool(hints.get("github")) or bool(hints.get("linkedin"))

        for email in hints.get("emails", []) or []:
            if email in by_email:
                uf.union(i, by_email[email])
            else:
                by_email[email] = i

        for kind in ("github", "linkedin"):
            handle = hints.get(kind)
            if not handle:
                continue
            key = f"{kind}:{handle}"
            if key in by_handle:
                uf.union(i, by_handle[key])
            else:
                by_handle[key] = i

        # Name fallback only links records with NO strong identifier, to avoid merging two
        # different people who merely share a name.
        name = hints.get("name")
        if name and not has_strong:
            if name in by_name:
                uf.union(i, by_name[name])
            else:
                by_name[name] = i

    groups: dict[int, list[SourceRecord]] = defaultdict(list)
    for i, rec in enumerate(records):
        groups[uf.find(i)].append(records[i])
    # Stable ordering: by the smallest original index in each group.
    return [groups[root] for root in sorted(groups)]


# ================================================================= field merging
def merge_group(records: list[SourceRecord]) -> CanonicalProfile:
    claims_by_field: dict[str, list[Claim]] = defaultdict(list)
    for rec in records:
        for claim in rec.claims:
            claims_by_field[claim.field].append(claim)

    profile = CanonicalProfile()
    provenance: list[dict[str, str]] = []
    field_conf: dict[str, float] = {}

    # ---- scalar single-value fields
    for field in ("full_name", "headline", "years_experience"):
        winner = _resolve_scalar(claims_by_field.get(field, []))
        if winner:
            setattr(profile, field, winner["value"])
            field_conf[field] = winner["confidence"]
            provenance.append({"field": field, "source": winner["source"], "method": winner["method"]})

    # ---- list fields: emails, phones
    for field in ("emails", "phones"):
        values, conf, prov = _resolve_scalar_list(claims_by_field.get(field, []))
        if values:
            setattr(profile, field, values)
            field_conf[field] = conf
            provenance.extend({"field": field, **p} for p in prov)

    # ---- skills (special list-of-objects with per-skill confidence + sources)
    skills, skills_conf, skills_prov = _resolve_skills(claims_by_field.get("skills", []))
    if skills:
        profile.skills = skills
        field_conf["skills"] = skills_conf
        provenance.extend({"field": "skills", **p} for p in skills_prov)

    # ---- location (field-wise best across claims)
    location, loc_conf, loc_prov = _resolve_location(claims_by_field.get("location", []))
    if location:
        profile.location = location
        field_conf["location"] = loc_conf
        if loc_prov:
            provenance.append({"field": "location", **loc_prov})

    # ---- links (sub-field best + union of 'other')
    links, links_conf, links_prov = _resolve_links(
        claims_by_field.get("links.linkedin", []),
        claims_by_field.get("links.github", []),
        claims_by_field.get("links.portfolio", []),
        claims_by_field.get("links.other", []),
    )
    profile.links = links
    if links_conf:
        field_conf["links"] = links_conf
    provenance.extend({"field": "links", **p} for p in links_prov)

    # ---- experience / education (dedup union)
    profile.experience, exp_conf, exp_prov = _resolve_experience(claims_by_field.get("experience", []))
    if profile.experience:
        field_conf["experience"] = exp_conf
        provenance.append({"field": "experience", **exp_prov})
    profile.education, edu_conf, edu_prov = _resolve_education(claims_by_field.get("education", []))
    if profile.education:
        field_conf["education"] = edu_conf
        provenance.append({"field": "education", **edu_prov})

    # ---- identity + rollups
    profile.candidate_id = _candidate_id(profile)
    profile.field_confidence = {k: round(v, 4) for k, v in field_conf.items()}
    profile.overall_confidence = _overall_confidence(field_conf)
    profile.provenance = _dedup_provenance(provenance)
    return profile


# ------------------------------------------------------------------ scalar logic
def _resolve_scalar(claims: list[Claim]) -> dict | None:
    if not claims:
        return None
    by_value: dict[Any, list[Claim]] = defaultdict(list)
    for c in claims:
        by_value[_value_key(c.value)].append(c)

    scored = []
    for key, group in by_value.items():
        best = max(group, key=lambda c: (c.base_confidence, -sourcerank.source_priority(c.source)))
        distinct_sources = len({sourcerank.source_type_of(c.source) for c in group})
        score = best.base_confidence + AGREEMENT_BONUS * (distinct_sources - 1)
        scored.append((score, best, distinct_sources))

    scored.sort(key=lambda t: (-t[0], sourcerank.source_priority(t[1].source), str(t[1].value)))
    top_score, top_claim, top_sources = scored[0]
    confidence = min(CONF_CAP, top_claim.base_confidence + AGREEMENT_BONUS * (top_sources - 1))
    # Conflict: a different value scores almost as high -> we're less sure.
    if len(scored) > 1 and (top_score - scored[1][0]) < CONFLICT_MARGIN:
        confidence *= (1 - CONFLICT_PENALTY)
    return {"value": top_claim.value, "confidence": round(confidence, 4),
            "source": top_claim.source, "method": top_claim.method}


def _resolve_scalar_list(claims: list[Claim]):
    """Dedup union for emails/phones. Returns (values, field_confidence, provenance[])."""
    if not claims:
        return [], 0.0, []
    by_value: dict[Any, list[Claim]] = defaultdict(list)
    order: list[Any] = []
    for c in claims:
        k = _value_key(c.value)
        if k not in by_value:
            order.append(k)
        by_value[k].append(c)

    entries = []
    for k in order:
        group = by_value[k]
        best = max(group, key=lambda c: c.base_confidence)
        distinct = len({sourcerank.source_type_of(c.source) for c in group})
        conf = min(CONF_CAP, best.base_confidence + AGREEMENT_BONUS * (distinct - 1))
        entries.append((best.value, conf, best.source, best.method))

    entries.sort(key=lambda e: (-e[1], str(e[0])))  # confidence desc, then deterministic
    values = [e[0] for e in entries]
    provenance = [{"source": e[2], "method": e[3]} for e in entries]
    field_conf = round(max(e[1] for e in entries), 4)
    return values, field_conf, provenance


def _resolve_skills(claims: list[Claim]):
    if not claims:
        return [], 0.0, []
    by_name: dict[str, list[Claim]] = defaultdict(list)
    order: list[str] = []
    for c in claims:
        name = c.value["name"] if isinstance(c.value, dict) else str(c.value)
        if name not in by_name:
            order.append(name)
        by_name[name].append(c)

    skills = []
    provenance = []
    prov_seen = set()
    for name in order:
        group = by_name[name]
        distinct_sources = sorted({sourcerank.source_type_of(c.source) for c in group})
        best = max(group, key=lambda c: c.base_confidence)
        conf = min(CONF_CAP, best.base_confidence + AGREEMENT_BONUS * (len(distinct_sources) - 1))
        skills.append({"name": name, "confidence": round(conf, 4), "sources": distinct_sources})
        for c in group:
            key = (c.source, c.method)
            if key not in prov_seen:
                prov_seen.add(key)
                provenance.append({"source": c.source, "method": c.method})

    skills.sort(key=lambda s: (-s["confidence"], s["name"]))
    field_conf = round(max(s["confidence"] for s in skills), 4)
    return skills, field_conf, provenance


def _resolve_location(claims: list[Claim]):
    if not claims:
        return None, 0.0, None
    # Field-wise best for city/region/country across all location claims.
    best_by_part: dict[str, tuple[float, str, Claim]] = {}
    for c in claims:
        if not isinstance(c.value, dict):
            continue
        for part in ("city", "region", "country"):
            val = c.value.get(part)
            if val and (part not in best_by_part or c.base_confidence > best_by_part[part][0]):
                best_by_part[part] = (c.base_confidence, val, c)
    if not best_by_part:
        return None, 0.0, None
    location = {part: best_by_part.get(part, (0, None, None))[1] for part in ("city", "region", "country")}
    primary = max(best_by_part.values(), key=lambda t: t[0])[2]
    conf = round(min(CONF_CAP, primary.base_confidence), 4)
    return location, conf, {"source": primary.source, "method": primary.method}


def _resolve_links(linkedin, github, portfolio, other):
    links = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    conf_vals, provenance = [], []
    for key, claims in (("linkedin", linkedin), ("github", github), ("portfolio", portfolio)):
        if claims:
            best = max(claims, key=lambda c: c.base_confidence)
            links[key] = best.value
            conf_vals.append(best.base_confidence)
            provenance.append({"source": best.source, "method": best.method})
    seen = set()
    for c in other:
        if c.value not in seen:
            seen.add(c.value)
            links["other"].append(c.value)
    field_conf = round(min(CONF_CAP, max(conf_vals)), 4) if conf_vals else 0.0
    return links, field_conf, provenance


def _resolve_experience(claims: list[Claim]):
    jobs, conf = _dedup_records(
        claims, key=lambda v: (_company_key(v.get("company")), _norm(v.get("title"))),
        fill_order=("company", "title", "start", "end", "summary"))
    jobs = _drop_bare_duplicates(jobs)
    jobs.sort(key=lambda j: (j.get("end") != "present", j.get("start") or "", j.get("company") or ""),
              reverse=True)
    return jobs, conf, _first_prov(claims)


def _resolve_education(claims: list[Claim]):
    edus, conf = _dedup_records(
        claims, key=lambda v: (_norm(v.get("institution")), _norm(v.get("degree"))),
        fill_order=("institution", "degree", "field", "end_year"))
    edus.sort(key=lambda e: (e.get("end_year") or 0), reverse=True)
    return edus, conf, _first_prov(claims)


def _dedup_records(claims: list[Claim], key, fill_order):
    """Merge list-of-dict claims: dedup by `key`, filling missing sub-fields from lower-conf
    duplicates so we keep the richest version of each entry."""
    if not claims:
        return [], 0.0
    merged: dict[Any, dict] = {}
    best_conf: dict[Any, float] = {}
    for c in sorted(claims, key=lambda c: -c.base_confidence):
        if not isinstance(c.value, dict):
            continue
        k = key(c.value)
        if k == (None, None):
            continue
        if k not in merged:
            merged[k] = {f: c.value.get(f) for f in fill_order}
            best_conf[k] = c.base_confidence
        else:
            for f in fill_order:
                if not merged[k].get(f) and c.value.get(f):
                    merged[k][f] = c.value[f]
    conf = round(min(CONF_CAP, max(best_conf.values())), 4) if best_conf else 0.0
    return list(merged.values()), conf


# ------------------------------------------------------------------------ helpers
def _drop_bare_duplicates(jobs: list[dict]) -> list[dict]:
    """Remove "company only" stub jobs (e.g. a GitHub `company` field) when a richer entry
    for the same company already exists — they add no information."""
    companies_with_detail = {
        _company_key(j.get("company")) for j in jobs if j.get("title") or j.get("start")
    }
    return [
        j for j in jobs
        if (j.get("title") or j.get("start") or _company_key(j.get("company")) not in companies_with_detail)
    ]


def _value_key(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _norm(s: Any) -> str:
    return str(s).strip().lower() if s else ""


def _company_key(s: Any) -> str:
    """Punctuation/spacing-insensitive company key so "analytical-engines" == "Analytical Engines"."""
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", str(s).lower()) if s else ""


def _first_prov(claims: list[Claim]) -> dict[str, str]:
    if not claims:
        return {"source": "", "method": ""}
    best = max(claims, key=lambda c: c.base_confidence)
    return {"source": best.source, "method": best.method}


def _overall_confidence(field_conf: dict[str, float]) -> float:
    if not field_conf:
        return 0.0
    num = sum(field_conf[f] * _OVERALL_WEIGHTS.get(f, 0.5) for f in field_conf)
    den = sum(_OVERALL_WEIGHTS.get(f, 0.5) for f in field_conf)
    return round(num / den, 4) if den else 0.0


def _candidate_id(profile: CanonicalProfile) -> str:
    basis = profile.emails[0] if profile.emails else (profile.full_name or "")
    digest = hashlib.sha1(basis.lower().encode("utf-8")).hexdigest()[:12]
    return f"cand_{digest}"


def _dedup_provenance(provenance: list[dict[str, str]]) -> list[dict[str, str]]:
    seen, out = set(), []
    for p in provenance:
        key = (p["field"], p["source"], p["method"])
        if key not in seen:
            seen.add(key)
            out.append(p)
    return sorted(out, key=lambda p: (p["field"], p["source"]))
