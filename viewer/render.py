"""Pure helpers for the viewer: page images with boxes, and table <-> model conversion."""

import io

import pandas as pd
import pymupdf
from PIL import Image, ImageDraw

from extract.lines import extract_page_lines
from extract.models import Component, HardwareSet

RENDER_DPI = 110
SET_COLOR = (37, 99, 235)       # blue: the set's location on this page
ROW_COLOR = (234, 88, 12)       # orange: lines of the selected component
TABLE_COLUMNS = ["qty", "description", "catalog_number", "mfr", "finish", "notes"]


def line_boxes(doc: pymupdf.Document, page: int, line_ids: list[str]) -> list[tuple]:
    """Bboxes of the given line IDs on a 1-based page (IDs are stable per page)."""
    wanted = set(line_ids)
    return [line.bbox for line in extract_page_lines(doc[page - 1]) if line.id in wanted]


def render_page(doc: pymupdf.Document, page: int, set_boxes: list[tuple],
                row_boxes: list[tuple] = ()) -> Image.Image:
    """The page as an image, with set boxes (blue) and component line boxes (orange).
    Boxes are in PDF points and are scaled to the render DPI here."""
    pix = doc[page - 1].get_pixmap(dpi=RENDER_DPI)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    draw = ImageDraw.Draw(image)
    scale = RENDER_DPI / 72
    for boxes, color, width, pad in ((set_boxes, SET_COLOR, 3, 4), (row_boxes, ROW_COLOR, 2, 1)):
        for x0, y0, x1, y1 in boxes:
            draw.rectangle([(x0 - pad) * scale, (y0 - pad) * scale,
                            (x1 + pad) * scale, (y1 + pad) * scale], outline=color, width=width)
    return image


def components_to_rows(hw: HardwareSet) -> list[dict]:
    """Editable rows; 'check' lists low-confidence fields so a reviewer looks there first."""
    return [{**{c: getattr(comp, c) for c in TABLE_COLUMNS},
             "check": ", ".join(f for f, v in sorted(comp.field_confidence.items()) if v < 1)}
            for comp in hw.components]


def _clean(value):
    """Table cells come back as NaN/NA/'' for empty; the models want None."""
    if value is None or (not isinstance(value, str) and pd.isna(value)) or \
            (isinstance(value, str) and not value.strip()):
        return None
    return value.strip() if isinstance(value, str) else value


def rows_to_components(rows: list[dict], original: HardwareSet) -> list[Component]:
    """Apply edited rows to the set. Rows keep their line IDs and confidences by
    position; an edited field is human-checked, so its low-confidence flag is dropped.
    Raises pydantic.ValidationError for invalid values (e.g. qty 0)."""
    out = []
    for i, row in enumerate(rows):
        values = {c: _clean(row.get(c)) for c in TABLE_COLUMNS}
        if values["description"] is None:
            continue  # blank row left over from adding/deleting in the editor
        if i < len(original.components):
            before = original.components[i]
            edited = {c for c in TABLE_COLUMNS if values[c] != getattr(before, c)}
            confidence = {f: v for f, v in before.field_confidence.items() if f not in edited}
            out.append(Component(**values, source_line_ids=before.source_line_ids,
                                 field_confidence=confidence))
        else:
            out.append(Component(**values))  # added by the reviewer: no source lines
    return out
