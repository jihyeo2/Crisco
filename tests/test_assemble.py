from extract.assemble import assemble, strip_mfr_prefix
from extract.lines import Line
from extract.llm import LLMChunkResult, LLMComponent, LLMSet
from extract.models import Component, HardwareSet, SetStatus


def line(page, idx, y, text, x0=74.0, x1=300.0):
    return Line(f"p{page}_L{idx:03d}", page, (x0, y, x1, y + 11), text)


PAGE40 = [
    line(40, 1, 112, "Set: 12.0", 286, 329),
    line(40, 2, 184, "1 Surface Closer"),
    line(40, 3, 184, "Norton", 460, 493),
    line(40, 4, 200, "Hinge, Full Mortise"),
]
PAGE41 = [line(41, 1, 90, "1 Stop"), line(41, 2, 90, "Rockwood", 460, 510)]


def comp(ids, qty=1, desc="Surface Closer", **kw):
    return LLMComponent(qty=qty, description=desc, catalog_number=None, mfr=None,
                        finish=None, notes=None, line_ids=ids,
                        low_confidence_fields=kw.get("low", []))


def hwset(number, header, comps, status="active", conf=0.9):
    return LLMSet(set_number=number, description=None, status=status,
                  header_line_ids=header, components=comps, confidence=conf)


def run(*chunks):
    return assemble([(lines, LLMChunkResult(sets=sets)) for lines, sets in chunks])


def test_bbox_is_computed_per_page_from_line_ids():
    sets, _ = run((PAGE40 + PAGE41, [hwset("12.0", ["p40_L001"], [
        comp(["p40_L002", "p40_L003"]), comp(["p41_L001", "p41_L002"], desc="Stop")])]))
    [hw] = sets
    assert [(l.page, l.bbox) for l in hw.locations] == [
        (40, (74.0, 112.0, 493.0, 195.0)), (41, (74.0, 90.0, 510.0, 101.0))]


def test_unknown_line_ids_are_dropped_and_confidence_capped():
    sets, warnings = run((PAGE40, [hwset("12.0", ["p40_L001", "p99_L001"], [
        comp(["p40_L002", "p40_L777"])], conf=0.95)]))
    [hw] = sets
    assert hw.components[0].source_line_ids == ["p40_L002"]
    assert hw.confidence == 0.5
    assert any("unknown line IDs" in w for w in warnings)


def test_component_without_valid_evidence_is_dropped():
    sets, warnings = run((PAGE40, [hwset("12.0", ["p40_L001"], [comp(["p77_L001"])])]))
    assert sets[0].components == []
    assert any("dropped component" in w for w in warnings)


def test_qty_not_printed_becomes_null():
    # "Hinge, Full Mortise" has no number: a model-guessed 3 must not survive
    sets, warnings = run((PAGE40, [hwset("12.0", ["p40_L001"], [
        comp(["p40_L004"], qty=3, desc="Hinge, Full Mortise")])]))
    assert sets[0].components[0].qty is None
    assert any("not found" in w for w in warnings)


def test_printed_qty_kept_and_low_confidence_fields_mapped():
    sets, _ = run((PAGE40, [hwset("12.0", ["p40_L001"], [
        comp(["p40_L002", "p40_L003"], low=["finish"])])]))
    c = sets[0].components[0]
    assert c.qty == 1 and c.field_confidence == {"finish": 0.5}


def test_not_used_set_is_kept():
    sets, _ = run((PAGE40, [hwset("07", ["p40_L001"], [], status="not_used")]))
    assert sets[0].status is SetStatus.NOT_USED


def test_overlapping_chunks_merge_same_set_without_duplicate_rows():
    first = (PAGE40, [hwset("12.0", ["p40_L001"], [comp(["p40_L002", "p40_L003"])])])
    second = (PAGE40 + PAGE41, [hwset("12.0", ["p40_L001"], [
        comp(["p40_L002", "p40_L003"]), comp(["p41_L001", "p41_L002"], desc="Stop")])])
    sets, _ = run(first, second)
    [hw] = sets
    assert [c.description for c in hw.components] == ["Surface Closer", "Stop"]
    assert [l.page for l in hw.locations] == [40, 41]


def test_same_number_far_apart_is_not_merged():
    far = [line(90, 1, 100, "Set: 12.0"), line(90, 2, 120, "1 Stop")]
    sets, _ = run((PAGE40, [hwset("12.0", ["p40_L001"], [comp(["p40_L002"])])]),
                  (far, [hwset("12.0", ["p90_L001"], [comp(["p90_L002"], desc="Stop")])]))
    assert len(sets) == 2


def test_unknown_rows_already_covered_by_a_named_set_are_dropped():
    first = (PAGE40 + PAGE41, [hwset("12.0", ["p40_L001"], [
        comp(["p40_L002"]), comp(["p41_L001", "p41_L002"], desc="Stop")])])
    second = (PAGE41, [hwset("UNKNOWN", [], [comp(["p41_L001", "p41_L002"], desc="Stop")])])
    sets, _ = run(first, second)
    assert [s.set_number for s in sets] == ["12.0"]


def test_strip_mfr_prefix_only_removes_the_repeated_manufacturer():
    def one(mfr, cat):
        s = HardwareSet(set_number="1", components=[Component(description="x", mfr=mfr, catalog_number=cat)])
        return strip_mfr_prefix([s])[0].components[0].catalog_number
    assert one("IVES", 'IVES - 5BB1 4.5" x 4.5"') == '5BB1 4.5" x 4.5"'
    assert one("VON DUPRIN", "von duprin \u2013 6200 SERIES") == "6200 SERIES"
    assert one("LCN", "4040XP - EDA ARM") == "4040XP - EDA ARM"      # no prefix: untouched
    assert one("IVES", "IVESTON - 1") == "IVESTON - 1"              # mfr must be the whole prefix
    assert one(None, "IVES - 5BB1") == "IVES - 5BB1"                # no mfr: untouched
