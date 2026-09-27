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


def format_for_prompt(lines: list[Line]) -> str:
    """One line per row: ID, left x and top y (for column/row structure), text."""
    out, current_page = [], None
    for line in lines:
        if line.page != current_page:
            current_page = line.page
            out.append(f"=== PAGE {current_page} ===")
        x0, y0 = line.bbox[:2]
        out.append(f"{line.id}  x={x0:.0f} y={y0:.0f}  {line.text}")
    return "\n".join(out)
