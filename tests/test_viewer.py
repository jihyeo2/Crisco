import pymupdf

from extract.models import Component, HardwareSet, Location
from viewer.render import components_to_rows, focus_clip, render_page, rows_to_components, to_data_uri

HW = HardwareSet(set_number="12.0", locations=[Location(page=1, bbox=(50, 50, 200, 120))], components=[
    Component(qty=None, description="Hinge", catalog_number="TA2714", mfr="McKinney",
              source_line_ids=["p1_L002"], field_confidence={"qty": 0.5}),
    Component(qty=1, description="Stop", catalog_number="RM860", mfr="Rockwood",
              source_line_ids=["p1_L003"], field_confidence={"mfr": 0.8, "notes": 0.5}),
])


def test_rows_round_trip_and_show_flags():
    rows = components_to_rows(HW)
    assert rows[0]["check"] == "qty" and rows[1]["check"] == "mfr, notes"
    assert rows_to_components(rows, HW) == HW.components


def test_edit_clears_that_fields_flag_and_keeps_line_ids():
    rows = components_to_rows(HW)
    rows[1]["mfr"] = "ROCKWOOD"
    stop = rows_to_components(rows, HW)[1]
    assert stop.mfr == "ROCKWOOD" and stop.field_confidence == {"notes": 0.5}
    assert stop.source_line_ids == ["p1_L003"]


def test_blank_cells_become_none_and_added_rows_have_no_lines():
    rows = components_to_rows(HW) + [{"qty": float("nan"), "description": "Silencers",
                                      "catalog_number": "", "mfr": None, "finish": None, "notes": None}]
    added = rows_to_components(rows, HW)[2]
    assert added.qty is None and added.catalog_number is None and added.source_line_ids == []


def test_render_page_draws_boxes():
    doc = pymupdf.open()
    doc.new_page(width=300, height=200).insert_text((60, 80), "Set: 12.0")
    plain = render_page(doc, 1, [])
    boxed = render_page(doc, 1, [(50, 50, 200, 120)], [(55, 70, 120, 85)])
    assert plain.size == boxed.size and plain.tobytes() != boxed.tobytes()


def test_zoom_renders_larger_and_focus_crops_to_the_set():
    doc = pymupdf.open()
    doc.new_page(width=300, height=200).insert_text((60, 80), "Set: 12.0")
    full = render_page(doc, 1, [(50, 50, 200, 120)])
    zoomed = render_page(doc, 1, [(50, 50, 200, 120)], zoom=2.0)
    assert abs(zoomed.size[0] - 2 * full.size[0]) <= 2   # pixel rounding
    clip = focus_clip(doc[0].rect, [(50, 50, 200, 120)], margin=24)
    assert clip == (26, 26, 224, 144)
    cropped = render_page(doc, 1, [(50, 50, 200, 120)], clip=clip)
    assert cropped.size[0] < full.size[0] and cropped.size[1] < full.size[1]
    assert focus_clip(doc[0].rect, [(5, 5, 290, 195)], margin=24) == (0, 0, 300, 200)  # stays on page
    assert to_data_uri(cropped).startswith("data:image/jpeg;base64,")
