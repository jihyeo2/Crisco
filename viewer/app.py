"""Review extracted hardware sets against the PDF, correct them, export JSON.

    streamlit run viewer/app.py

No API calls: extraction is done with `python -m extract <pdf> -o out/<name>.json`.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # streamlit only puts viewer/ on the path

import pandas as pd  # noqa: E402
import pymupdf  # noqa: E402
import streamlit as st  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from extract.models import ExtractionResult, SetStatus  # noqa: E402
from viewer.render import (TABLE_COLUMNS, components_to_rows, focus_clip,  # noqa: E402
                           line_boxes, render_page, rows_to_components, to_data_uri)

st.set_page_config(page_title="Hardware Set Review", layout="wide")
PAGE_BOX_HEIGHT = 820  # px; the page scrolls inside this box when zoomed


# --- load ---------------------------------------------------------------------

@st.cache_resource
def open_pdf(path: str) -> pymupdf.Document:
    return pymupdf.open(path)


def load_result() -> tuple[str, ExtractionResult] | None:
    st.sidebar.header("Output")
    # examples/ ships with the repo so the viewer works without running extraction
    files = sorted(str(p.relative_to(ROOT)) for d in ("examples", "out")
                   for p in (ROOT / d).rglob("*.json"))
    upload = st.sidebar.file_uploader("…or upload an output JSON", type="json")
    if upload is not None:
        return upload.name, ExtractionResult.model_validate_json(upload.getvalue())
    if not files:
        st.info("No outputs under examples/ or out/. "
                "Run `python -m extract <pdf> -o out/<name>.json` first.")
        return None
    choice = st.sidebar.selectbox("Output JSON", files)
    return choice, ExtractionResult.model_validate_json((ROOT / choice).read_text())


loaded = load_result()
if loaded is None:
    st.stop()
key, original = loaded

# Edits live in session state per output file, so switching sets keeps them.
# The table editor records edits relative to the data it was first given, so it is
# always fed the *original* set; bumping "version" resets every editor.
if st.session_state.get("loaded_key") != key:
    st.session_state.loaded_key = key
    st.session_state.result = original.model_copy(deep=True)
    st.session_state.version = 0
result: ExtractionResult = st.session_state.result

pdf_path = ROOT / result.source_pdf
if not pdf_path.exists():
    st.error(f"Source PDF not found: {result.source_pdf}")
    st.stop()
doc = open_pdf(str(pdf_path))

# --- pick a set -----------------------------------------------------------------

def label(i: int) -> str:
    hw = result.sets[i]
    flags = sum(v < 1 for c in hw.components for v in c.field_confidence.values())
    tag = " · NOT USED" if hw.status is SetStatus.NOT_USED else ""
    return f"{hw.set_number}{tag} · conf {hw.confidence:.2f} · {flags} flagged"

st.sidebar.header("Set")
index = st.sidebar.selectbox("Hardware set", range(len(result.sets)), format_func=label)
base = original.sets[index]   # what the editor is fed
hw = result.sets[index]       # current, with edits

st.sidebar.caption(f"{Path(result.source_pdf).name}: {len(result.sets)} sets, "
                   f"{sum(len(s.components) for s in result.sets)} components")

# --- page + table ---------------------------------------------------------------

st.subheader(f"Set {hw.set_number}" + (f": {hw.description}" if hw.description else ""))
if hw.status is SetStatus.NOT_USED:
    st.warning("NOT USED: kept for the record; don't price it.")
if hw.confidence < 0.7:
    st.warning(f"Low set confidence ({hw.confidence:.2f}): check it against the page.")

left, right = st.columns([5, 6])

with right:
    st.markdown("**Components** · edit cells, add or delete rows; *check* lists low-confidence fields")
    edited = st.data_editor(
        pd.DataFrame(components_to_rows(base), columns=["check", *TABLE_COLUMNS]),
        key=f"editor-{key}-{index}-{st.session_state.version}",
        num_rows="dynamic",
        hide_index=True,
        column_order=["check", *TABLE_COLUMNS],
        column_config={
            "check": st.column_config.TextColumn("check", disabled=True, width="small"),
            "qty": st.column_config.NumberColumn("qty", min_value=0.0, step=1.0,
                                                 help="Empty = not printed; never guessed"),
        },
    )
    try:
        components = rows_to_components(edited.to_dict("records"), base)
        hw = base.model_copy(update={"components": components})
        result.sets[index] = hw
    except ValidationError as e:
        st.error(f"Not saved: {e.errors()[0]['loc'][0]}: {e.errors()[0]['msg']}")

    row_choice = st.selectbox(
        "Highlight a component's lines on the page", [None, *range(len(hw.components))],
        format_func=lambda i: "—" if i is None else
        f"{i + 1}. {hw.components[i].description}")

with left:
    pages = [loc.page for loc in hw.locations] or [None]
    page = st.radio("Page", pages, horizontal=True) if len(pages) > 1 else pages[0]
    if page is None:
        st.info("This set has no location on the page.")
    else:
        set_boxes = [loc.bbox for loc in hw.locations if loc.page == page]
        row_ids = hw.components[row_choice].source_line_ids if row_choice is not None else []
        zoom_col, focus_col = st.columns([3, 2])
        zoom = zoom_col.select_slider("Zoom", options=[1.0, 1.5, 2.0, 3.0], value=1.0,
                                      format_func=lambda z: f"{z:.0%}")
        focus = focus_col.toggle("Focus on set", value=False, disabled=not set_boxes)
        clip = focus_clip(doc[page - 1].rect, set_boxes) if focus and set_boxes else None
        image = render_page(doc, page, set_boxes, line_boxes(doc, page, row_ids), zoom, clip)
        # A fixed-height box that scrolls both ways, so a zoomed page can be panned.
        st.markdown(
            f'<div style="height:{PAGE_BOX_HEIGHT}px; overflow:auto; '
            f'border:1px solid rgba(128,128,128,.35); border-radius:4px">'
            f'<img src="{to_data_uri(image)}" style="width:{zoom * 100:.0f}%; '
            f'max-width:none; display:block"></div>', unsafe_allow_html=True)
        st.caption(f"Page {page} · blue = set, orange = selected component"
                   " · scroll inside the box to pan")

# --- export -----------------------------------------------------------------------

st.sidebar.header("Export")
try:
    payload = ExtractionResult.model_validate(result.model_dump()).model_dump_json(indent=2)
    st.sidebar.download_button("Download corrected JSON", payload,
                               file_name=Path(key).stem + ".reviewed.json",
                               mime="application/json")
except ValidationError as e:
    st.sidebar.error(f"Fix errors before export: {e.errors()[0]['msg']}")
if st.sidebar.button("Discard all edits"):
    st.session_state.result = original.model_copy(deep=True)
    st.session_state.version += 1
    st.rerun()
