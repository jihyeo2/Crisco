"""Turn per-chunk LLM answers into validated HardwareSets.

- Line IDs the model cites are checked against the lines it was actually sent;
  unknown IDs are dropped, and anything left with no evidence is discarded.
- A qty must appear as a number in the component's own lines, or it becomes null.
- Bboxes are computed here from line IDs: one rectangle per page per set.
- Sets seen in several (overlapping) chunks are merged.
"""

import re
from collections import defaultdict

from extract.lines import Line
from extract.llm import LLMChunkResult, LLMComponent, LLMSet
from extract.models import Component, HardwareSet, Location, SetStatus

# Confidence given to fields the model flagged as uncertain, and the cap on a
# set's confidence when the model cited line IDs that don't exist.
LOW_FIELD_CONFIDENCE = 0.5
BAD_EVIDENCE_CONFIDENCE_CAP = 0.5

NUMBER = re.compile(r"\d+(?:\.\d+)?")
UNKNOWN = "UNKNOWN"  # set_number the model uses when the header isn't in its chunk


def line_sort_key(line_id: str) -> tuple[int, int]:
    page, index = line_id[1:].split("_L")
    return int(page), int(index)


def qty_is_printed(qty: float, lines: list[Line]) -> bool:
    return any(float(n) == qty for line in lines for n in NUMBER.findall(line.text))


def compute_locations(line_ids: list[str], by_id: dict[str, Line]) -> list[Location]:
    boxes: dict[int, list[tuple[float, float, float, float]]] = defaultdict(list)
    for lid in line_ids:
        line = by_id[lid]
        boxes[line.page].append(line.bbox)
    return [
        Location(page=page, bbox=(min(b[0] for b in bs), min(b[1] for b in bs),
                                  max(b[2] for b in bs), max(b[3] for b in bs)))
        for page, bs in sorted(boxes.items())
    ]


def build_component(raw: LLMComponent, by_id: dict[str, Line],
                    warnings: list[str]) -> Component | None:
    ids = sorted({i for i in raw.line_ids if i in by_id}, key=line_sort_key)
    if not ids:
        warnings.append(f"dropped component {raw.description!r}: no valid line IDs")
        return None
    field_confidence = {f: LOW_FIELD_CONFIDENCE for f in raw.low_confidence_fields}

    qty = raw.qty
    if qty is not None and (qty <= 0 or not qty_is_printed(qty, [by_id[i] for i in ids])):
        warnings.append(f"qty {qty} for {raw.description!r} not found in its lines; set to null")
        qty = None
        field_confidence.pop("qty", None)

    return Component(
        qty=qty, description=raw.description, catalog_number=raw.catalog_number,
        mfr=raw.mfr, finish=raw.finish, notes=raw.notes,
        source_line_ids=ids, field_confidence=field_confidence,
    )


def build_set(raw: LLMSet, by_id: dict[str, Line], warnings: list[str]) -> HardwareSet | None:
    cited = set(raw.header_line_ids) | {i for c in raw.components for i in c.line_ids}
    unknown = cited - by_id.keys()

    components = [c for c in (build_component(rc, by_id, warnings) for rc in raw.components) if c]
    header_ids = sorted({i for i in raw.header_line_ids if i in by_id}, key=line_sort_key)
    all_ids = header_ids + [i for c in components for i in c.source_line_ids]
    if not all_ids:
        warnings.append(f"dropped set {raw.set_number!r}: no valid line IDs")
        return None

    confidence = min(max(raw.confidence, 0.0), 1.0)
    if unknown:
        warnings.append(f"set {raw.set_number!r} cited {len(unknown)} unknown line IDs")
        confidence = min(confidence, BAD_EVIDENCE_CONFIDENCE_CAP)

    return HardwareSet(
        set_number=raw.set_number.strip(), description=raw.description,
        status=SetStatus(raw.status), locations=compute_locations(all_ids, by_id),
        components=components, source_line_ids=header_ids, confidence=confidence,
    )


def _pages(hw: HardwareSet) -> set[int]:
    return {loc.page for loc in hw.locations}


def _evidence(hw: HardwareSet) -> int:
    return len(hw.source_line_ids) + sum(len(c.source_line_ids) for c in hw.components)


def merge_sets(a: HardwareSet, b: HardwareSet, by_id: dict[str, Line]) -> HardwareSet:
    """Combine two partial views of one set. Components that share a line are the
    same row; keep the view that cites more lines."""
    main, other = (a, b) if _evidence(a) >= _evidence(b) else (b, a)
    components = list(main.components)
    for comp in other.components:
        ids = set(comp.source_line_ids)
        clash = next((i for i, c in enumerate(components) if ids & set(c.source_line_ids)), None)
        if clash is None:
            components.append(comp)
        elif len(ids) > len(components[clash].source_line_ids):
            components[clash] = comp
    components.sort(key=lambda c: line_sort_key(c.source_line_ids[0]))

    header_ids = sorted(set(main.source_line_ids) | set(other.source_line_ids), key=line_sort_key)
    all_ids = header_ids + [i for c in components for i in c.source_line_ids]
    return main.model_copy(update={
        "description": main.description or other.description,
        "components": components,
        "source_line_ids": header_ids,
        "locations": compute_locations(all_ids, by_id),
        "confidence": min(main.confidence, other.confidence),
    })


def assemble(chunk_results: list[tuple[list[Line], LLMChunkResult]]) -> tuple[list[HardwareSet], list[str]]:
    """chunk_results: (lines sent, model answer) per chunk, in page order."""
    warnings: list[str] = []
    by_id_all: dict[str, Line] = {}
    merged: list[HardwareSet] = []

    for lines, result in chunk_results:
        by_id = {line.id: line for line in lines}
        by_id_all.update(by_id)
        for raw in result.sets:
            hw = build_set(raw, by_id, warnings)
            if hw is None:
                continue
            # Same number on the same or an adjacent page = the same set seen twice.
            match = next((i for i, m in enumerate(merged)
                          if m.set_number == hw.set_number
                          and any(abs(p - q) <= 1 for p in _pages(m) for q in _pages(hw))), None)
            if match is None:
                merged.append(hw)
            else:
                merged[match] = merge_sets(merged[match], hw, by_id_all)

    merged = _resolve_unknown(merged, by_id_all, warnings)
    merged.sort(key=lambda s: min(line_sort_key(i) for i in
                                  s.source_line_ids + [c.source_line_ids[0] for c in s.components]))
    return merged, warnings


def _resolve_unknown(sets: list[HardwareSet], by_id: dict[str, Line],
                     warnings: list[str]) -> list[HardwareSet]:
    """A chunk that starts mid-set reports those rows under "UNKNOWN". The
    overlapping previous chunk usually saw them under the real set number, so drop
    UNKNOWN rows already covered there and keep only what nothing else explains."""
    covered = {i for s in sets if s.set_number != UNKNOWN
               for c in s.components for i in c.source_line_ids}
    out = []
    for s in sets:
        if s.set_number != UNKNOWN:
            out.append(s)
            continue
        rest = [c for c in s.components if not covered & set(c.source_line_ids)]
        if rest:
            warnings.append(f"{len(rest)} component(s) with no visible set header kept as UNKNOWN")
            ids = s.source_line_ids + [i for c in rest for i in c.source_line_ids]
            out.append(s.model_copy(update={
                "components": rest, "locations": compute_locations(ids, by_id),
                "confidence": min(s.confidence, BAD_EVIDENCE_CONFIDENCE_CAP)}))
    return out
