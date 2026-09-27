"""Classify a single mfr/finish value, using only the PDF being processed.

These per-value classifications are votes: resolve.py labels each printed column
by the majority of its values, and the column decides. Sources, most trusted first:
1. The document's own legends ("Manufacturer's Abbreviations", "Hardware Finish
   List", ...), parsed from its text.
2. A small seed of general industry knowledge (see SEED_* below).

Values are only classified here, never rewritten: output keeps what's printed.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

import pymupdf

from extract.lines import extract_page_lines, group_rows

Kind = Literal["mfr", "finish", "ambiguous", "unknown"]

# Seed: only votes for labeling columns (resolve.py); a column's majority decides.
# Kept to general industry knowledge, not names picked up from the sample specbooks,
# so the eval (step 5) measures generalization rather than our own tuning.
#
# Manufacturers: widely used names and their conventional 3-letter abbreviations
# (as in DHI "Abbreviations and Symbols"). No 2-letter codes: spec writers define
# those themselves (BE = Best in one spec, DO = Don Jo in another).
SEED_MFR = {
    "IVE", "IVES", "SCH", "SCE", "SCHLAGE", "VON", "VON DUPRIN", "LCN", "ZER", "ZERO",
    "SAR", "SARGENT", "GLY", "GLYNN-JOHNSON", "BES", "BEST", "HAG", "HAGER",
    "MCK", "MCKINNEY", "ROC", "ROCKWOOD", "PEM", "PEMKO", "NOR", "NORTON",
    "TRI", "TRIMCO", "RIX", "RIXSON", "ADAMS RITE", "HES", "SELECT",
    "DORMA", "MEDECO", "ASSA ABLOY", "ALLEGION", "YALE", "CORBIN RUSSWIN", "STANLEY",
}
# Finishes: generic color/material words, plus the BHMA and US finish-code formats
# from the published standard ANSI/BHMA A156.18 (same in every spec).
SEED_FINISH_WORDS = {
    "BLACK", "BLK", "GREY", "GRAY", "GRY", "CLEAR", "CLR", "WHITE", "WHT",
    "MILL", "ALUM", "PRIME", "DKB", "BRONZE",
}
SEED_FINISH_PATTERNS = [
    re.compile(r"^[3-7]\d{2}[A-Z]?$"),      # BHMA: 313, 626, 630, 689, 613E
    re.compile(r"^US\d{1,2}[A-Z]{0,2}$"),   # US26D, US32D, US10B
]
# Codes seen with both meanings; only a legend or column position can settle them.
# AA: clear anodized aluminum / ASSA ABLOY. AL: aluminum / Alarm Lock.
# PE, NO: named as ambiguous in the problem statement (Pemko / Norton).
SEED_AMBIGUOUS = {"AA", "AL", "PE", "NO"}


@dataclass
class Legend:
    """Codes a document defines for itself: code -> printed name/description."""
    mfr: dict[str, str] = field(default_factory=dict)
    finish: dict[str, str] = field(default_factory=dict)


def first_token(value: str) -> str:
    """'613 (OIL RUBBED BRONZE)' -> '613', 'PEMKO / NGP / ZERO' -> 'PEMKO'."""
    return re.split(r"[\s(/,]+", value.strip().upper(), maxsplit=1)[0]


def classify(value: str | None, legend: Legend | None = None) -> Kind:
    if not value or not value.strip():
        return "unknown"
    legend = legend or Legend()
    whole, token = value.strip().upper(), first_token(value)

    in_mfr = whole in legend.mfr or token in legend.mfr
    in_finish = whole in legend.finish or token in legend.finish
    if in_mfr != in_finish:
        return "mfr" if in_mfr else "finish"
    if in_mfr and in_finish:
        return "ambiguous"

    if token in SEED_AMBIGUOUS:
        return "ambiguous"
    if whole in SEED_MFR or token in SEED_MFR:
        return "mfr"
    if token in SEED_FINISH_WORDS or any(p.match(token) for p in SEED_FINISH_PATTERNS):
        return "finish"
    return "unknown"


# --- legend parsing ---------------------------------------------------------

MFR_HEADING = re.compile(r"manufacturer\S*\s+(abbreviations|legend|list|key|codes)", re.I)
FINISH_HEADING = re.compile(r"finish(es)?\s+(list|legend|key|codes|abbreviations)", re.I)
LETTERED_HEADING = re.compile(r"^[A-Z]\.(\s|$)")   # "D. Option List" starts the next subsection
# A legend heading is a short line; longer text is prose that merely mentions
# "manufacturers' abbreviations".
MAX_HEADING_CHARS = 60
ENUMERATOR = re.compile(r"^\d+\.$")                  # "1."
CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,7}$")      # "PE", "MED1", "10BE", "VA01"
CODE_AND_NAME = re.compile(r"^([A-Z0-9][A-Z0-9-]{0,7})\s+([A-Z][a-z].*)$")  # "MED1 Medeco"
# Page footers/headers can interrupt a list; give up after this many non-entry rows.
MAX_NOISE_ROWS = 6


def parse_entry(cells: list[str]) -> tuple[str, str] | None:
    if cells and ENUMERATOR.match(cells[0]):
        cells = cells[1:]
    if len(cells) >= 2 and CODE.match(cells[0]):
        return cells[0], " ".join(cells[1:])
    if len(cells) == 1 and (m := CODE_AND_NAME.match(cells[0])):
        return m.group(1), m.group(2)
    return None


def parse_legend_rows(rows: list[list[str]]) -> Legend:
    """rows: visual rows (cells left to right) of consecutive pages, in order."""
    legend = Legend()
    target: dict[str, str] | None = None
    noise = 0
    for cells in rows:
        text = " ".join(cells)
        if len(text) <= MAX_HEADING_CHARS:
            if MFR_HEADING.search(text):
                target, noise = legend.mfr, 0
                continue
            if FINISH_HEADING.search(text):
                target, noise = legend.finish, 0
                continue
        if target is None:
            continue
        if LETTERED_HEADING.match(text):
            target = None
            continue
        entry = parse_entry(cells)
        if entry:
            target.setdefault(entry[0].upper(), entry[1])
            noise = 0
        else:
            noise += 1
            if noise > MAX_NOISE_ROWS:
                target = None
    return legend


# Legends sit in the hardware section, before the sets. Look this far back from
# the first set page.
LEGEND_LOOKBACK_PAGES = 60


def find_legend(doc: pymupdf.Document, set_pages: list[int]) -> Legend:
    if not set_pages:
        return Legend()
    first, last = max(1, set_pages[0] - LEGEND_LOOKBACK_PAGES), set_pages[-1]
    rows = [[line.text for line in row]
            for p in range(first, last + 1)
            for row in group_rows(extract_page_lines(doc[p - 1]))]
    return parse_legend_rows(rows)
