import pytest
from pydantic import ValidationError

from extract.models import Component, ExtractionResult, HardwareSet, Location, SetStatus


def closer(**overrides) -> Component:
    fields = dict(qty=1, description="Surface Closer", catalog_number="R 7500",
                  mfr="Norton", source_line_ids=["p40_L020", "p40_L021"])
    return Component(**(fields | overrides))


def test_valid_set_round_trips_through_json():
    hw = HardwareSet(
        set_number="12.0",
        description="Passage function with closer - single",
        locations=[Location(page=40, bbox=(74, 112, 493, 268))],
        components=[closer(field_confidence={"qty": 0.95, "finish": 0.4})],
        source_line_ids=["p40_L010"],
        confidence=0.9,
    )
    result = ExtractionResult(source_pdf="087100.pdf", sets=[hw])
    assert ExtractionResult.model_validate_json(result.model_dump_json()) == result


def test_missing_qty_is_null_not_guessed():
    assert closer(qty=None).qty is None


def test_fractional_qty_allowed():
    assert closer(qty=1.5).qty == 1.5


@pytest.mark.parametrize("qty", [0, -1])
def test_non_positive_qty_rejected(qty):
    with pytest.raises(ValidationError):
        closer(qty=qty)


def test_not_used_set_keeps_number_but_no_components():
    hw = HardwareSet(set_number="07", status=SetStatus.NOT_USED)
    assert hw.status is SetStatus.NOT_USED and hw.components == []
    with pytest.raises(ValidationError, match="not_used"):
        HardwareSet(set_number="07", status="not_used", components=[closer()])


@pytest.mark.parametrize("line_id", ["p40L12", "L012", "p40_L1", "40_L012"])
def test_malformed_line_ids_rejected(line_id):
    with pytest.raises(ValidationError):
        closer(source_line_ids=[line_id])


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        HardwareSet(set_number="1", confidence=1.2)
    with pytest.raises(ValidationError):
        closer(field_confidence={"mfr": -0.1})


def test_unknown_field_confidence_key_rejected():
    with pytest.raises(ValidationError):
        closer(field_confidence={"colour": 0.5})


def test_bbox_corners_must_be_ordered():
    with pytest.raises(ValidationError):
        Location(page=1, bbox=(100, 50, 10, 60))
