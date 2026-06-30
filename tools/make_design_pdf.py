"""Render DESIGN.md into the one-page Step-1 PDF deliverable.

Deliberately small and self-contained: parses the subset of Markdown used in DESIGN.md
(H1/H2, bullets, **bold**, `code`) and lays it out with fpdf2, tuned to fit a single A4 page.

    python tools/make_design_pdf.py

Output: "Aryan Ghai_aryanghai1205@gmail.com_Eightfold.pdf" in the repo root.
"""
from __future__ import annotations

import os
import re

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "DESIGN.md")
OUT = os.path.join(ROOT, "Aryan Ghai_aryanghai1205@gmail.com_Eightfold.pdf")

NAVY = (16, 42, 82)
GREY = (90, 90, 90)
BLACK = (20, 20, 20)


_UNICODE_FOLD = {
    "—": "-", "–": "-", "→": "->", "×": "x", "·": "-",
    "≤": "<=", "≥": ">=", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...",
}


def _clean_inline(text: str) -> str:
    # fpdf core fonts are latin-1; fold the few Unicode glyphs we use to ASCII. Drop backticks
    # (inline `code` -> plain) and ** markers (we set bold via fonts, not fpdf's markdown mode,
    # which mis-wraps long lines).
    for uni, ascii_ in _UNICODE_FOLD.items():
        text = text.replace(uni, ascii_)
    return text.replace("`", "").replace("*", "")


class Design(FPDF):
    def header(self):  # no running header
        pass


def build() -> None:
    with open(SRC, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    pdf = Design(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.set_margins(14, 11, 14)
    pdf.add_page()

    def cell(text, h, indent=0.0):
        """Full-width wrapped paragraph that always returns the cursor to the left margin."""
        if indent:
            pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, h, _clean_inline(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    for raw in lines:
        line = raw.rstrip()
        if not line:
            pdf.ln(1.3)
            continue

        if line.startswith("# "):
            pdf.set_text_color(*NAVY)
            pdf.set_font("Helvetica", "B", 15)
            cell(line[2:], 6.8)
            pdf.ln(0.4)
        elif line.startswith("## "):
            pdf.ln(0.8)
            pdf.set_text_color(*NAVY)
            pdf.set_font("Helvetica", "B", 10.5)
            cell(line[3:], 4.8)
            pdf.set_draw_color(*NAVY)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(0.9)
        elif line.startswith("- "):
            pdf.set_text_color(*BLACK)
            pdf.set_font("Helvetica", "", 8.6)
            cell("- " + line[2:], 3.9, indent=2.5)
        elif re.match(r"^\*\*.+\*\*$", line) and pdf.get_y() < 40:
            pdf.set_text_color(*GREY)
            pdf.set_font("Helvetica", "I", 9)
            cell(line.strip("*"), 4.4)
        else:
            pdf.set_text_color(*BLACK)
            pdf.set_font("Helvetica", "", 8.6)
            cell(line, 3.95)

    pdf.output(OUT)
    print(f"wrote {OUT}  ({pdf.page_no()} page[s])")


if __name__ == "__main__":
    build()
