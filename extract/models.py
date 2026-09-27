"""Data models for extracted door hardware sets.

Coordinates never come from the model: every set and component carries the IDs of
the text lines it was read from (e.g. "p40_L012"), and our code turns those into
page bounding boxes.
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
    NOT_USED = "not_used"


class Location(BaseModel):
    """Where (part of) a set sits on one page, in PDF points, origin top-left."""

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
    source_line_ids: list[LineId] = Field(default_factory=list)
    field_confidence: dict[ComponentField, Confidence] = Field(default_factory=dict)


class HardwareSet(BaseModel):
    set_number: str  # string: "12.0", "3.3", "HW-04" all occur
    description: str | None = None
    status: SetStatus = SetStatus.ACTIVE
    locations: list[Location] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    source_line_ids: list[LineId] = Field(default_factory=list)
    confidence: Confidence = 1.0

    @model_validator(mode="after")
    def _not_used_has_no_components(self) -> "HardwareSet":
        if self.status is SetStatus.NOT_USED and self.components:
            raise ValueError(f"set {self.set_number} is not_used but has components")
        return self


class ExtractionResult(BaseModel):
    """Top-level output of `python -m extract <pdf> -o out.json`."""

    source_pdf: str
    sets: list[HardwareSet] = Field(default_factory=list)
