"""Resume extractor (unstructured prose: .txt/.md, .docx, .pdf).

Text loading is format-aware but dependency-light:
  * .txt/.md       -> read directly.
  * .docx          -> parsed with the standard-library `zipfile`+`xml` (no third-party dep);
                      a .docx is just a zip of XML, so we pull the `<w:t>` runs.
  * .pdf           -> uses `pdfminer`/`pypdf` *if installed*; otherwise we skip the file
                      gracefully (a missing optional dependency must never crash the run).

Parsing then splits the text into labelled sections (SKILLS / EXPERIENCE / EDUCATION) and
reads contact details from the header. One resume == one candidate.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
import zipfile

from ..handles import github_handle, linkedin_handle
from ..models import SourceRecord
from .base import Extractor

_EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+?\d[\d\-\.\s()]{7,}\d)")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+", re.IGNORECASE)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_]+", re.IGNORECASE)
# A job header line: "Senior Engineer, Acme Corp (2018-03 - 2021-06)" or "Acme — Engineer | 2018–2021"
_JOB_LINE = re.compile(
    r"^(?P<a>[A-Z][\w&.\-/+ ]{2,50}?)\s*[,–—|@\-]\s*(?P<b>[A-Z][\w&.\-/+ ]{2,50}?)\s*"
    r"[\(\[|\-–—]?\s*(?P<dates>(?:[A-Za-z]{3,9}\.?\s*)?\d{4}(?:[-/]\d{1,2})?)\s*"
    r"[-–—to ]+\s*(?P<end>present|current|(?:[A-Za-z]{3,9}\.?\s*)?\d{4}(?:[-/]\d{1,2})?)",
    re.IGNORECASE)

_SECTION_HEADERS = {
    "skills": ("skills", "technical skills", "core skills", "technologies"),
    "experience": ("experience", "work experience", "employment", "professional experience"),
    "education": ("education", "academic background"),
}


class ResumeExtractor(Extractor):
    source_type = "resume"

    def extract(self, path: str) -> list[SourceRecord]:
        src = self.source_id(path)
        text = self._load_text(path)
        if not text or not text.strip():
            return []

        rec = SourceRecord(source=src)
        lines = [ln.rstrip() for ln in text.splitlines()]
        nonempty = [ln.strip() for ln in lines if ln.strip()]

        # Name: first non-empty line that looks like a person's name.
        if nonempty:
            first = nonempty[0]
            if re.fullmatch(r"[A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+){1,3}", first):
                rec.add("full_name", first, method="resume_section")

        emails = _dedup(m.group(0) for m in _EMAIL.finditer(text))
        for e in emails:
            rec.add("emails", e, method="regex_email")
        for ph in _phones(text):
            rec.add("phones", ph, method="regex_phone")

        li = _LINKEDIN.search(text)
        if li:
            rec.add("links.linkedin", li.group(0), method="resume_regex")
        gh = _GITHUB.search(text)
        if gh:
            rec.add("links.github", gh.group(0), method="resume_regex")

        sections = self._split_sections(lines)

        for skill in _split_skills(sections.get("skills", "")):
            rec.add("skills", skill, method="resume_section")

        for job in self._parse_experience(sections.get("experience", "")):
            rec.add("experience", job, method="resume_section")

        for edu in self._parse_education(sections.get("education", "")):
            rec.add("education", edu, method="resume_section")

        rec.match_hints = {
            "emails": emails,
            "name": nonempty[0] if nonempty else None,
            "github": github_handle(gh.group(0)) if gh else None,
            "linkedin": linkedin_handle(li.group(0)) if li else None,
        }
        return [rec] if rec.claims else []

    # ---------------------------------------------------------------- text loading
    def _load_text(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".docx":
                return _read_docx(path)
            if ext == ".pdf":
                return _read_pdf(path)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except Exception:
            return ""  # any loader failure -> treat as empty source, never crash

    # ---------------------------------------------------------------- sectioning
    def _split_sections(self, lines: list[str]) -> dict[str, str]:
        header_of = {}
        for canon, names in _SECTION_HEADERS.items():
            for n in names:
                header_of[n] = canon

        sections: dict[str, list[str]] = {}
        current = None
        for ln in lines:
            key = ln.strip().lower().rstrip(":").strip()
            if key in header_of:
                current = header_of[key]
                sections.setdefault(current, [])
                continue
            if current:
                sections[current].append(ln)
        return {k: "\n".join(v).strip() for k, v in sections.items()}

    def _parse_experience(self, block: str) -> list[dict]:
        jobs = []
        for raw in block.splitlines():
            line = raw.strip().lstrip("•-*").strip()
            m = _JOB_LINE.match(line)
            if m:
                a, b = m.group("a").strip(), m.group("b").strip()
                # Heuristic: the token containing typical title words is the title.
                title, company = (a, b)
                if re.search(r"\b(engineer|developer|manager|scientist|lead|architect|intern|analyst|designer)\b",
                             b, re.IGNORECASE) and not re.search(
                             r"\b(engineer|developer|manager|scientist|lead|architect|intern|analyst|designer)\b",
                             a, re.IGNORECASE):
                    title, company = b, a
                jobs.append({"company": company, "title": title,
                             "start": m.group("dates"), "end": m.group("end"), "summary": None})
        return jobs

    def _parse_education(self, block: str) -> list[dict]:
        edus = []
        for raw in block.splitlines():
            line = raw.strip().lstrip("•-*").strip()
            if not line:
                continue
            year = None
            ym = re.search(r"(19|20)\d{2}", line)
            if ym:
                year = ym.group(0)
            degree = None
            dm = re.search(r"\b(B\.?S\.?|B\.?Tech|M\.?S\.?|M\.?Tech|Ph\.?D|Bachelor|Master|MBA|B\.?A\.?|M\.?A\.?)[\w.]*",
                           line, re.IGNORECASE)
            if dm:
                degree = dm.group(0)
            field = None
            fm = re.search(r"\bin\s+([A-Z][A-Za-z &]+?)(?:,|\(|$|\s+\d)", line)
            if fm:
                field = fm.group(1).strip()
            # institution = the leading chunk before a comma
            institution = line.split(",")[0].strip() if "," in line else (
                line if not degree else None)
            edus.append({"institution": institution, "degree": degree,
                         "field": field, "end_year": year})
        return edus


# ----------------------------------------------------------------- format loaders
def _read_docx(path: str) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for para in root.iter(f"{ns}p"):
        runs = [node.text for node in para.iter(f"{ns}t") if node.text]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def _read_pdf(path: str) -> str:
    """Best-effort PDF text via an optional dependency. Returns "" if none is installed."""
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        return extract_text(path) or ""
    except Exception:
        pass
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(path)
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    except Exception:
        return ""


def _phones(text: str) -> list[str]:
    out = []
    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 7 <= len(digits) <= 15:
            out.append(m.group(0).strip())
    return _dedup(out)


def _split_skills(block: str) -> list[str]:
    if not block:
        return []
    block = block.replace("\n", ",")
    block = re.sub(r"\b(and|with)\b", ",", block, flags=re.IGNORECASE)
    parts = re.split(r"[,;|•·]", block)
    return [p.strip() for p in parts if p.strip()]


def _dedup(items) -> list[str]:
    seen, out = set(), []
    for it in items:
        key = it.lower()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
