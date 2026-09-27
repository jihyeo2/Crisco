"""Put manufacturer and finish values in the right fields, using only this PDF.

1. Classify each value with the document's legend, then the standard seed
   (codes.classify).
2. Values that stay ambiguous or unknown are decided by *where they're printed*:
   the known mfr and finish values in the same set (or, if the set has too few, the
   whole document) show where this spec's mfr and finish columns sit, and the
   undecided value goes to the nearer one. This is a vote across the column,
   never a per-value guess.
3. Still undecided: keep the model's choice and mark the field low-confidence.
"""

import re
from statistics import median

from extract.codes import Kind, Legend, classify, first_token
from extract.lines import Line
from extract.models import Component, HardwareSet

POSITION_CONFIDENCE = 0.8   # decided by column position, not by a code list
UNDECIDED_CONFIDENCE = 0.5  # nothing in the document could decide it

Centers = dict[str, float]  # {"mfr": x, "finish": x}


def value_x(value: str, comp: Component, by_id: dict[str, Line]) -> float | None:
    """Approximate x where `value` is printed among the component's lines.
    A line holding several cells ("622 FH") is split proportionally by characters."""
    token = re.escape(first_token(value))
    for lid in comp.source_line_ids:
        line = by_id.get(lid)
        if line is None:
            continue
        m = re.search(rf"(?<![A-Z0-9]){token}(?![A-Z0-9])", line.text.upper())
        if m:
            x0, _, x1, _ = line.bbox
            return x0 + (x1 - x0) * m.start() / max(len(line.text), 1)
    return None


def column_centers(components: list[Component], by_id: dict[str, Line],
                   legend: Legend) -> Centers:
    xs: dict[str, list[float]] = {"mfr": [], "finish": []}
    for comp in components:
        for value in (comp.mfr, comp.finish):
            kind = classify(value, legend)
            if kind in xs and (x := value_x(value, comp, by_id)) is not None:
                xs[kind].append(x)
    return {k: median(v) for k, v in xs.items() if v}


def decide(value: str, comp: Component, by_id: dict[str, Line], legend: Legend,
           centers: Centers) -> tuple[Kind | None, bool]:
    """(kind or None if undecided, decided_by_position)"""
    kind = classify(value, legend)
    if kind in ("mfr", "finish"):
        return kind, False
    x = value_x(value, comp, by_id)
    if x is None or len(centers) < 2 or centers["mfr"] == centers["finish"]:
        return None, False
    return min(centers, key=lambda k: abs(centers[k] - x)), True


def resolve_component(comp: Component, by_id: dict[str, Line], legend: Legend,
                      centers: Centers, warnings: list[str]) -> Component:
    slots = {"mfr": comp.mfr, "finish": comp.finish}
    decided: dict[str, tuple[Kind | None, bool]] = {
        f: decide(v, comp, by_id, legend, centers) for f, v in slots.items() if v}
    if not decided:
        return comp

    new = {"mfr": None, "finish": None}
    confidence = dict(comp.field_confidence)
    leftovers = []
    for field, (kind, by_position) in decided.items():
        if kind and new[kind] is None:
            new[kind] = slots[field]
            confidence.pop(kind, None)
            if by_position:
                confidence[kind] = POSITION_CONFIDENCE
        else:
            leftovers.append(field)
    for field in leftovers:  # undecided (or a clash): keep the model's field if free
        target = field if new[field] is None else ("finish" if field == "mfr" else "mfr")
        new[target] = slots[field]
        confidence[target] = UNDECIDED_CONFIDENCE

    if new != slots:
        warnings.append(f"{comp.description!r}: mfr/finish {slots} -> {new}")
    return comp.model_copy(update={**new, "field_confidence": confidence})


def resolve_mfr_finish(sets: list[HardwareSet], by_id: dict[str, Line],
                       legend: Legend) -> tuple[list[HardwareSet], list[str]]:
    warnings: list[str] = []
    doc_centers = column_centers([c for s in sets for c in s.components], by_id, legend)
    out = []
    for hw in sets:
        set_centers = column_centers(hw.components, by_id, legend)
        centers = set_centers if len(set_centers) == 2 else doc_centers
        components = [resolve_component(c, by_id, legend, centers, warnings)
                      for c in hw.components]
        out.append(hw.model_copy(update={"components": components}))
    return out, warnings
