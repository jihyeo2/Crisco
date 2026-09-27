"""Put manufacturer and finish values in the right fields from their column.

Context decides, not individual values:
1. Find the columns: a value's position is (x where its cell starts, which word of
   the cell it is), so "622 FH" printed in one cell is still two columns. Cells
   starting less than COLUMN_GAP apart, at the same word, are one column.
2. Label each column by majority vote of its values, classified with this PDF's
   legend and the standard seed (codes.classify). "Mostly IVE, LCN, SCH" makes a
   manufacturer column; "mostly 626, 630" a finish column. A set with too few votes
   borrows the label of the document-level column at the same x. If only one kind
   of column is labeled, the largest unlabeled column is the other kind.
3. Every value takes its column's label, e.g. PE printed in the finish column is a
   finish, whatever it means elsewhere.
4. Values in no labeled column (a stray "No", or no position found) fall back to
   their own classification; if that can't decide either, the model's field is kept
   and marked low-confidence.
"""

import re
from collections import Counter
from dataclasses import dataclass
from statistics import median

from extract.codes import Legend, classify, first_token
from extract.lines import Line
from extract.models import Component, HardwareSet

# Measured on 4 specs: values in one column start within 13 pt of each other
# (centered names spread the most); separate columns are >= 41 pt apart.
COLUMN_GAP = 20.0
MIN_INFERRED_COLUMN = 2       # values needed before an unlabeled column is inferred

COLUMN_CONFIDENCE = 0.8       # value's own code was ambiguous/unknown; its column decided
OVERRIDE_CONFIDENCE = 0.6     # value's own code said the opposite; its column won
UNDECIDED_CONFIDENCE = 0.5    # nothing could decide; model's field kept

FIELDS = ("mfr", "finish")
OTHER = {"mfr": "finish", "finish": "mfr"}


@dataclass
class Point:
    comp: int          # index into the component list
    field: str         # field the model put the value in
    value: str
    x: float | None    # x where the value's cell (line) starts
    word: int          # which word of that cell the value starts at
    kind: str          # classify() result for the value alone


@dataclass
class Column:
    word: int
    xs: list[float]
    votes: Counter
    label: str | None = None

    @property
    def x(self) -> float:
        return median(self.xs)


def value_position(value: str, comp: Component,
                   by_id: dict[str, Line]) -> tuple[float | None, int]:
    """(x where the cell holding `value` starts, word index of `value` in that cell)."""
    token = re.escape(first_token(value))
    for lid in comp.source_line_ids:
        line = by_id.get(lid)
        if line is None:
            continue
        m = re.search(rf"(?<![A-Z0-9]){token}(?![A-Z0-9])", line.text.upper())
        if m:
            return line.bbox[0], len(line.text[:m.start()].split())
    return None, 0


def collect_points(components: list[Component], by_id: dict[str, Line],
                   legend: Legend) -> list[Point]:
    return [Point(i, f, v, *value_position(v, c, by_id), classify(v, legend))
            for i, c in enumerate(components)
            for f in FIELDS if (v := getattr(c, f))]


def find_columns(points: list[Point]) -> list[Column]:
    located = sorted((p for p in points if p.x is not None), key=lambda p: (p.word, p.x))
    columns: list[Column] = []
    for p in located:
        last = columns[-1] if columns else None
        if last and last.word == p.word and p.x - last.xs[-1] < COLUMN_GAP:
            last.xs.append(p.x)
        else:
            columns.append(Column(p.word, [p.x], Counter()))
        if p.kind in FIELDS:
            columns[-1].votes[p.kind] += 1
    return columns


def label_columns(columns: list[Column], fallback: list[Column] | None = None) -> None:
    for col in columns:
        top = col.votes.most_common(2)
        if top and (len(top) == 1 or top[0][1] > top[1][1]):
            col.label = top[0][0]
        elif fallback and (near := column_of(col.x, col.word, fallback)):
            col.label = near.label
    kinds = {c.label for c in columns if c.label}
    unlabeled = [c for c in columns if not c.label and len(c.xs) >= MIN_INFERRED_COLUMN]
    if len(kinds) == 1 and unlabeled:
        max(unlabeled, key=lambda c: len(c.xs)).label = OTHER[kinds.pop()]


def column_of(x: float | None, word: int, columns: list[Column]) -> Column | None:
    candidates = [c for c in columns if c.word == word]
    if x is None or not candidates:
        return None
    col = min(candidates, key=lambda c: abs(c.x - x))
    return col if abs(col.x - x) < COLUMN_GAP else None


def resolve_set(hw: HardwareSet, by_id: dict[str, Line], legend: Legend,
                doc_columns: list[Column], warnings: list[str]) -> HardwareSet:
    points = collect_points(hw.components, by_id, legend)
    columns = find_columns(points)
    label_columns(columns, fallback=doc_columns)

    # decide each value's field
    placed: dict[int, list[tuple[Point, str | None, float | None]]] = {}
    for p in points:
        col = column_of(p.x, p.word, columns)
        if col and col.label:
            if p.kind == col.label:
                decision = (col.label, None)
            elif p.kind in FIELDS:
                decision = (col.label, OVERRIDE_CONFIDENCE)
                warnings.append(f"set {hw.set_number}: {p.value!r} reads as {p.kind} "
                                f"but is printed in the {col.label} column")
            else:
                decision = (col.label, COLUMN_CONFIDENCE)
        elif p.kind in FIELDS:
            decision = (p.kind, None)
        else:
            decision = (None, UNDECIDED_CONFIDENCE)
        placed.setdefault(p.comp, []).append((p, *decision))

    components = list(hw.components)
    for i, decisions in placed.items():
        components[i] = apply(components[i], decisions, hw.set_number, warnings)
    return hw.model_copy(update={"components": components})


def apply(comp: Component, decisions: list[tuple[Point, str | None, float | None]],
          set_number: str, warnings: list[str]) -> Component:
    new: dict[str, str | None] = {"mfr": None, "finish": None}
    confidence = {k: v for k, v in comp.field_confidence.items() if k not in FIELDS}
    pending = []
    for p, target, conf in decisions:
        if target and new[target] is None:
            new[target] = p.value
            if conf is not None:
                confidence[target] = conf
        else:
            pending.append(p)
    for p in pending:  # undecided or clashing: keep the model's field if free
        target = p.field if new[p.field] is None else OTHER[p.field]
        new[target] = p.value
        confidence[target] = UNDECIDED_CONFIDENCE

    old = {"mfr": comp.mfr, "finish": comp.finish}
    if new != old:
        warnings.append(f"set {set_number}: {comp.description!r} mfr/finish {old} -> {new}")
    return comp.model_copy(update={**new, "field_confidence": confidence})


def resolve_mfr_finish(sets: list[HardwareSet], by_id: dict[str, Line],
                       legend: Legend) -> tuple[list[HardwareSet], list[str]]:
    warnings: list[str] = []
    all_components = [c for s in sets for c in s.components]
    doc_columns = find_columns(collect_points(all_components, by_id, legend))
    label_columns(doc_columns)
    return [resolve_set(s, by_id, legend, doc_columns, warnings) for s in sets], warnings
