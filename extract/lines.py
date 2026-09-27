"""Text lines with stable IDs and coordinates, the unit everything else refers to.

Each line gets an ID like "p40_L012" (page 40, 12th line on that page). The LLM
only ever sees and returns these IDs; bboxes are looked up here.
"""

from dataclasses import dataclass

import pymupdf


@dataclass(frozen=True)
class Line:
    id: str
    page: int  # 1-based
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points
    text: str


def line_id(page: int, index: int) -> str:
    return f"p{page}_L{index:03d}"


def extract_page_lines(page: pymupdf.Page) -> list[Line]:
    page_no = page.number + 1
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for raw in block.get("lines", []):  # image blocks have no "lines"
            text = "".join(span["text"] for span in raw["spans"]).strip()
            if not text:
                continue
            bbox = tuple(round(v, 1) for v in raw["bbox"])
            lines.append(Line(line_id(page_no, len(lines) + 1), page_no, bbox, text))
    return lines


def extract_lines(doc: pymupdf.Document, pages: list[int]) -> list[Line]:
    """Lines for the given 1-based page numbers, in page order."""
    return [line for p in pages for line in extract_page_lines(doc[p - 1])]


# Lines whose tops are within this many points are drawn on the same visual row.
ROW_TOLERANCE = 3.0


def group_rows(lines: list[Line]) -> list[list[Line]]:
    """Group one page's lines into visual rows (top to bottom), each sorted left
    to right, so table cells that PyMuPDF returns separately sit together again."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        if rows and abs(line.bbox[1] - rows[-1][0].bbox[1]) <= ROW_TOLERANCE:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [sorted(row, key=lambda l: l.bbox[0]) for row in rows]


def format_for_prompt(lines: list[Line]) -> str:
    """One visual row per text line: cells left to right, each tagged with its
    line ID and left x, e.g.
    `[p16_L020 x=74] MORTISE HINGE | [p16_L021 x=200] IVES - 5BB1 | [p16_L022 x=400] 2`
    """
    out = []
    for page in sorted({line.page for line in lines}):
        out.append(f"=== PAGE {page} ===")
        for row in group_rows([l for l in lines if l.page == page]):
            out.append(" | ".join(f"[{l.id} x={l.bbox[0]:.0f}] {l.text}" for l in row))
    return "\n".join(out)
