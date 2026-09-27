"""Data models for extracted door hardware sets.

Coordinates never come from the model: every set and component carries the IDs of
the text lines it was read from (e.g. "p40_L012"), and our code turns those into
page bounding boxes. A set's locations hold one bbox per page, the smallest
rectangle around all of that set's lines on the page (its own plus its components').
"""

import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator

LINE_ID_PATTERN = re.compile(r"^p\d+_L\d{3,}$")

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def _check_line_id(value: str) -> str:
    if not LINE_ID_PATTERN.match(value):
        raise ValueError(f"malformed line id {value!r}, expected like 'p12_L034'")
    return value


LineId = Annotated[str, AfterValidator(_check_line_id)]

ComponentField = Literal["qty", "description", "catalog_number", "mfr", "finish", "notes"]


class SetStatus(str, Enum):
    ACTIVE = "active"
    # Kept, never priced. A not_used set may still list the components the spec
    # left printed under it (e.g. "Set 07 — DELETED" over the old items).
    NOT_USED = "not_used"


class Location(BaseModel):
    """Where (part of) a set sits on one page, in PDF points, origin top-left.

    Derived from line IDs, never supplied by the model.
    """

    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1

    @model_validator(mode="after")
    def _check_bbox(self) -> "Location":
        x0, y0, x1, y1 = self.bbox
        if x0 > x1 or y0 > y1:
            raise ValueError(f"bbox corners out of order: {self.bbox}")
        return self


class Component(BaseModel):
    # Float because specs say things like "1.5 PR" of hinges. None when the spec
    # gives no quantity: never guess one.
    qty: float | None = Field(default=None, gt=0)
    description: str
    catalog_number: str | None = None
    mfr: str | None = None
    finish: str | None = None
    notes: str | None = None
    # Every line this component's values were read from.
    source_line_ids: list[LineId] = Field(default_factory=list)
    field_confidence: dict[ComponentField, Confidence] = Field(default_factory=dict)


class HardwareSet(BaseModel):
    set_number: str  # string: "12.0", "3.3", "HW-04" all occur
    description: str | None = None
    status: SetStatus = SetStatus.ACTIVE
    # One per page the set appears on; computed from set + component line IDs.
    locations: list[Location] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    # Lines for the set's own fields: set number, description, NOT USED marker.
    source_line_ids: list[LineId] = Field(default_factory=list)
    confidence: Confidence = 1.0


class ExtractionResult(BaseModel):
    """Top-level output of `python -m extract <pdf> -o out.json`."""

    source_pdf: str
    sets: list[HardwareSet] = Field(default_factory=list)
