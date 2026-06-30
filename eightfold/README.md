# Multi-Source Candidate Data Transformer

Turns messy, overlapping candidate data — recruiter **CSV**, **ATS JSON**, recruiter **notes**,
**resumes**, **GitHub** profiles — into **one clean, canonical, deduplicated profile per
candidate**, with **provenance** (where every value came from) and **confidence** (how much we
trust it). A runtime config then reshapes that canonical record into *any* output schema you ask
for — same engine, no code changes.

> Guiding rule: **wrong-but-confident is worse than honestly-empty.** A value we can't verify
> becomes `null` — it is never invented.

This repo is my submission for the Eightfold Engineering Intern (Jul–Dec 2026) assignment.
The one-page design is in [`DESIGN.md`](DESIGN.md) (and the PDF deliverable next to it);
a plain-language walkthrough of the whole thing is in [`GUIDE.md`](GUIDE.md).

---

## Quick start

```bash
# 1. (optional but recommended) create a virtual environment
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. install the one runtime dependency
pip install -r requirements.txt

# 3. run the pipeline on the sample inputs with the default schema
python -m transformer --inputs samples --config configs/default.json
```

`python -m transformer` needs the package on the path. Either:
- run with `PYTHONPATH=src` in front (e.g. `PYTHONPATH=src python -m transformer ...`), **or**
- install the project once: `pip install -e .`  → then just `transformer --inputs ...`.

> On Windows PowerShell, set the path with `$env:PYTHONPATH="src"` before the command, or use
> `pip install -e .`.

---

## Running it

**Default canonical schema** (full profile, with provenance + confidence):
```bash
python -m transformer --inputs samples --config configs/default.json -o output/profiles_default.json
```

**A custom output schema** — the exact example config from the assignment (flat recruiter view,
phone forced to E.164, skills to canonical names):
```bash
python -m transformer --inputs samples --config configs/custom_recruiter.json
```

**Another custom schema** — a compact export that *omits* missing fields and deep-remaps
(`location.country`, `links.github`):
```bash
python -m transformer --inputs samples --config configs/custom_compact_omit.json
```

**See the internal canonical record** (before projection):
```bash
python -m transformer --inputs samples --emit canonical
```

### CLI options
| Flag | Meaning |
|---|---|
| `--inputs, -i` | Input files, shell globs, or a directory to scan (CSV/JSON/TXT/DOCX/PDF). |
| `--config, -c` | Projection config JSON. Omit for the built-in default schema. |
| `--out, -o` | Write JSON here (default: stdout). |
| `--emit` | `output` (projected, default), `canonical` (internal record), or `both`. |
| `--as` | Force a source type, e.g. `--as samples/x.txt=recruiter_notes`. |
| `--fetch-github` | Allow live GitHub API calls (default: **offline**, cache only). |
| `--quiet, -q` | Suppress the stderr run summary. |

Exit code is `0` only if **every** candidate passes output validation (CI-friendly).

---

## What's in `samples/`
| File | Source type | Role in the demo |
|---|---|---|
| `recruiter_export.csv` | Recruiter CSV (structured) | Ada, Alan, Katherine. Has a garbage phone (`not-a-phone`). |
| `ats_dump.json` | ATS JSON (structured, foreign field names) | Ada (conflicting title) + Grace. |
| `notes/ada_notes.txt` | Recruiter notes (free text) | Reinforces Ada; adds a skill. |
| `resumes/alan_turing.txt` | Resume (prose) | Alan's skills, history, education. |
| `github_urls.txt` (+ `github_cache/`) | GitHub (API, cached for offline determinism) | Ada, Grace, Alan — linked by handle. |
| `malformed/broken_ats.json` | Deliberately broken | Proves a bad source warns, never crashes. |

These exercise the whole problem: **one structured + one unstructured** source (we ship four
source types), the same person across several sources with **conflicting values**, a
**garbage value**, a GitHub profile **with no email**, and a **malformed file**.

---

## How it works (one breath)
`detect → extract → normalize → resolve-identity → merge + confidence → project → validate`

1. **detect** the source type by sniffing content, not just the extension.
2. **extract** raw *claims* (`field, value, source, method`) — readers only observe, never crash.
3. **normalize** each claim to a canonical format (E.164 phones, `YYYY-MM` dates, ISO country,
   canonical skills) or drop it.
4. **resolve identity** — union-find groups records for the same person (by email and GitHub
   handle, not just name).
5. **merge + confidence** — pick a winner per field by source trust × method certainty; raise
   confidence when sources agree, lower it on conflict; record provenance.
6. **project** the canonical record into the requested schema.
7. **validate** the output against that schema before returning it.

Full reasoning is in [`DESIGN.md`](DESIGN.md); a guided tour of the code is in [`GUIDE.md`](GUIDE.md).

---

## Configurable output (the "twist")
The canonical record is always the same; a JSON **projection config** reshapes it with no code
change. A field spec can:
- **select** a subset of fields,
- **rename / remap** from a canonical path via `from` (`"emails[0]"`, `"skills[].name"`,
  `"location.country"`),
- **normalize** per field (`"E164"`, `"canonical"`, …),
- toggle `include_confidence` / `include_provenance`,
- choose `on_missing`: `"null"` | `"omit"` | `"error"`.

```json
{
  "fields": [
    { "path": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string", "required": true },
    { "path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164" },
    { "path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "on_missing": "null"
}
```
The projected output is validated against the field `type`/`required` rules before it's returned.

---

## Tests
```bash
pip install pytest
python -m pytest            # 96 tests: normalizers, skills, merge/identity, projection,
                            # validation, and an end-to-end golden + robustness + determinism
```
`tests/golden/default_profiles.json` is a checked-in gold profile; `test_pipeline.py` proves the
run is deterministic (order-independent) and that a malformed source can't crash it.

---

## Layout
```
src/transformer/         the engine
  detect.py              source-type sniffing
  extractors/            one reader per source type (csv, ats, notes, resume, github)
  normalize.py skills.py phone/date/country/skill normalizers (pure, well-tested)
  claim_normalize.py     applies the normalizers to extracted claims
  merge.py sourcerank.py identity resolution + confidence + provenance (the heart)
  projection.py          canonical record -> requested schema
  validation.py          output type/required checker
  pipeline.py cli.py      orchestration + command-line surface
configs/                 default + two custom projection configs
samples/                 demo inputs (see table above)
output/                  the JSON this repo produced on the samples
tests/                   the test suite + golden profile
DESIGN.md  GUIDE.md      one-page design + plain-language walkthrough
```

## Assumptions & scope
- **Offline & deterministic by default.** GitHub uses cached fixtures so runs are reproducible;
  `--fetch-github` opts into the live API.
- **Resume PDF** text needs an optional dep (`pip install pdfminer.six`); without it, PDF resumes
  are skipped with a warning (`.txt`, `.md`, `.docx` work out of the box — `.docx` via the stdlib).
- **LinkedIn** URLs are captured into `links`, not scraped (no public API).
- Identity matching is exact (normalized email / handle / name); fuzzy/ML matching is descoped.
- Built and tested on **Python 3.10+**.
