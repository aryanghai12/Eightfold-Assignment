"""Command-line surface.

    python -m transformer --inputs samples/* --config configs/default.json --out output/profiles.json

Point it at any number of input files (globs are expanded by your shell, or pass a directory
to include everything in it), give it a projection config, and it writes the projected JSON
(one object per candidate). Exit code is non-zero if any candidate fails validation, so the
CLI is CI-friendly.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .pipeline import run_pipeline


# Directories that hold support data, not inputs, when a folder is scanned recursively.
_SKIP_DIRS = {"github_cache", "__pycache__"}


def _expand_inputs(items: list[str]) -> list[str]:
    paths: list[str] = []
    for item in items:
        if os.path.isdir(item):
            for root, dirs, files in os.walk(item):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                paths.extend(os.path.join(root, f) for f in files)
        elif any(ch in item for ch in "*?["):
            paths.extend(glob.glob(item))
        else:
            paths.append(item)
    # de-dupe while preserving determinism
    return sorted({os.path.normpath(p) for p in paths if os.path.isfile(p)})


def _parse_overrides(items: list[str] | None) -> dict[str, str]:
    overrides = {}
    for item in items or []:
        if "=" in item:
            path, stype = item.split("=", 1)
            overrides[os.path.normpath(path.strip())] = stype.strip()
    return overrides


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transformer",
        description="Multi-Source Candidate Data Transformer — merge messy candidate "
                    "sources into one canonical profile and project it to any schema.")
    p.add_argument("--inputs", "-i", nargs="+", required=True,
                   help="Input files, globs, or directories (CSV / JSON / TXT / DOCX / PDF).")
    p.add_argument("--config", "-c", default=None,
                   help="Projection config JSON. Omit for the built-in default schema.")
    p.add_argument("--out", "-o", default=None,
                   help="Write projected JSON here. Defaults to stdout.")
    p.add_argument("--emit", choices=("output", "canonical", "both"), default="output",
                   help="What to print/write: projected 'output' (default), internal "
                        "'canonical' record, or 'both'.")
    p.add_argument("--as", dest="overrides", nargs="*", default=None,
                   help="Force a source type, e.g. --as notes.txt=recruiter_notes")
    p.add_argument("--fetch-github", action="store_true",
                   help="Allow live GitHub API calls (default: offline, cache-only).")
    p.add_argument("--quiet", "-q", action="store_true", help="Suppress the stderr run summary.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    inputs = _expand_inputs(args.inputs)
    if not inputs:
        print("error: no input files matched", file=sys.stderr)
        return 2

    config = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as fh:
            config = json.load(fh)

    result = run_pipeline(inputs, config, fetch_github=args.fetch_github,
                          type_overrides=_parse_overrides(args.overrides))

    if args.emit == "canonical":
        payload = [c.canonical for c in result.candidates]
    elif args.emit == "both":
        payload = [{"canonical": c.canonical, "output": c.output} for c in result.candidates]
    else:
        payload = [c.output for c in result.candidates if c.output is not None]

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)

    if not args.quiet:
        _print_summary(result, args.out)

    return 0 if result.ok else 1


def _print_summary(result, out_path) -> None:
    s = result.stats
    print("\n-- run summary --", file=sys.stderr)
    print(f"  input files     : {s.get('input_files')}", file=sys.stderr)
    print(f"  records         : {s.get('records_extracted')}  by source: {s.get('by_source')}",
          file=sys.stderr)
    print(f"  candidates      : {s.get('candidates')}", file=sys.stderr)
    print(f"  all valid       : {s.get('all_valid')}", file=sys.stderr)
    if out_path:
        print(f"  written to      : {out_path}", file=sys.stderr)
    for w in result.warnings:
        print(f"  ! {w}", file=sys.stderr)
    for c in result.candidates:
        for err in c.validation_errors:
            print(f"  x {c.canonical.get('candidate_id')}: {err}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
