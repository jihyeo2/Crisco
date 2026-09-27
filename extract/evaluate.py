"""Score an extraction output against hand-checked ground truth.

    python -m extract.evaluate out/jcryan.json eval/ground_truth/jcryan.json

Only ground truth marked "reviewed": true is scored (pass --include-unreviewed to
score drafts, clearly labeled as such). Reports:
- set recall / precision over the document's full list of set numbers
- component recall / precision within the scored sets
- per-field accuracy (qty, description, catalog_number, mfr, finish) on matched rows
- mfr/finish accuracy, plus how often mfr and finish were swapped
- guessed quantities: printed qty was blank but the output gave a number
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

FIELDS = ("qty", "description", "catalog_number", "mfr", "finish")
# Two rows match if their description + catalog tokens overlap at least this much.
MATCH_THRESHOLD = 0.3


def norm(value) -> str | None:
    """Case-, whitespace- and quote-insensitive text; qty compared as a number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    text = str(value).upper().replace("”", '"').replace("″", '"').replace("–", "-")
    return re.sub(r"\s+", "", text)


def tokens(comp: dict) -> set[str]:
    text = f"{comp.get('description') or ''} {comp.get('catalog_number') or ''}".upper()
    return set(re.findall(r"[A-Z0-9]+", text))


def similarity(a: dict, b: dict) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def match_components(truth: list[dict], pred: list[dict]) -> list[tuple[dict, dict]]:
    """Greedy one-to-one matching by token overlap, best pairs first."""
    pairs = sorted(((similarity(t, p), i, j) for i, t in enumerate(truth)
                    for j, p in enumerate(pred)), reverse=True)
    used_t, used_p, matched = set(), set(), []
    for score, i, j in pairs:
        if score < MATCH_THRESHOLD or i in used_t or j in used_p:
            continue
        used_t.add(i); used_p.add(j)
        matched.append((truth[i], pred[j]))
    return matched


@dataclass
class Report:
    label: str
    set_truth: int = 0
    set_found: int = 0
    set_pred: int = 0
    missing_sets: list[str] = field(default_factory=list)
    extra_sets: list[str] = field(default_factory=list)
    scored_sets: int = 0
    comp_truth: int = 0
    comp_pred: int = 0
    comp_matched: int = 0
    field_correct: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    mfr_finish_correct: int = 0
    mfr_finish_total: int = 0
    swapped: int = 0
    qty_blank_truth: int = 0
    qty_guessed: int = 0
    mismatches: list[str] = field(default_factory=list)

    def print(self) -> None:
        pct = lambda a, b: f"{a}/{b} ({100 * a / b:.0f}%)" if b else "n/a"
        print(f"== {self.label}")
        print(f"  set recall      {pct(self.set_found, self.set_truth)}")
        print(f"  set precision   {pct(self.set_found, self.set_pred)}")
        if self.missing_sets:
            print(f"    missing: {self.missing_sets}")
        if self.extra_sets:
            print(f"    extra:   {self.extra_sets}")
        print(f"  scored sets     {self.scored_sets}")
        print(f"  component recall    {pct(self.comp_matched, self.comp_truth)}")
        print(f"  component precision {pct(self.comp_matched, self.comp_pred)}")
        for f in FIELDS:
            print(f"    {f:15} {pct(self.field_correct[f], self.comp_matched)}")
        print(f"  mfr+finish both right {pct(self.mfr_finish_correct, self.mfr_finish_total)}"
              f"   swapped: {self.swapped}")
        print(f"  guessed qty (blank in PDF, number in output): "
              f"{self.qty_guessed} of {self.qty_blank_truth} blank")
        if self.mismatches:
            print("  mismatches:")
            for m in self.mismatches:
                print(f"    {m}")


def evaluate(output: dict, truth: dict, include_unreviewed: bool = False) -> Report:
    draft = include_unreviewed and not all(
        [truth.get("all_set_numbers_reviewed")] + [s.get("reviewed") for s in truth["sets"]])
    report = Report(label=Path(truth["source_pdf"]).name + ("  [UNREVIEWED DRAFT]" if draft else ""))
    pred_sets: dict[str, list[dict]] = {}
    for s in output["sets"]:
        pred_sets.setdefault(norm(s["set_number"]), []).extend(s["components"])

    if truth.get("all_set_numbers_reviewed") or include_unreviewed:
        truth_numbers = {norm(n): n for n in truth["all_set_numbers"]}
        report.set_truth, report.set_pred = len(truth_numbers), len(pred_sets)
        report.set_found = len(truth_numbers.keys() & pred_sets.keys())
        report.missing_sets = [n for k, n in truth_numbers.items() if k not in pred_sets]
        report.extra_sets = [s["set_number"] for s in output["sets"]
                             if norm(s["set_number"]) not in truth_numbers]

    for tset in truth["sets"]:
        if not (tset.get("reviewed") or include_unreviewed):
            continue
        report.scored_sets += 1
        truth_comps = tset["components"]
        pred_comps = pred_sets.get(norm(tset["set_number"]), [])
        report.comp_truth += len(truth_comps)
        report.comp_pred += len(pred_comps)
        report.qty_blank_truth += sum(c["qty"] is None for c in truth_comps)

        matched = match_components(truth_comps, pred_comps)
        matched_ids = {id(p) for _, p in matched}
        matched_truth = {id(t) for t, _ in matched}
        for t in truth_comps:
            if id(t) not in matched_truth:
                report.mismatches.append(f"set {tset['set_number']} missing row: {t['description']!r}")
        for p in pred_comps:
            if id(p) not in matched_ids:
                report.mismatches.append(f"set {tset['set_number']} extra row: {p['description']!r}")
        for t, p in matched:
            report.comp_matched += 1
            for f in FIELDS:
                if norm(t.get(f)) == norm(p.get(f)):
                    report.field_correct[f] += 1
                else:
                    report.mismatches.append(
                        f"set {tset['set_number']} {t['description']!r} {f}: "
                        f"expected {t.get(f)!r}, got {p.get(f)!r}")
            if t["qty"] is None and p.get("qty") is not None:
                report.qty_guessed += 1
            if t.get("mfr") or t.get("finish"):
                report.mfr_finish_total += 1
                if norm(t.get("mfr")) == norm(p.get("mfr")) and norm(t.get("finish")) == norm(p.get("finish")):
                    report.mfr_finish_correct += 1
                elif (t.get("mfr") and norm(t["mfr"]) == norm(p.get("finish"))) or \
                     (t.get("finish") and norm(t["finish"]) == norm(p.get("mfr"))):
                    report.swapped += 1
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Score extraction output against ground truth.")
    parser.add_argument("output", type=Path)
    parser.add_argument("truth", type=Path)
    parser.add_argument("--include-unreviewed", action="store_true",
                        help="also score ground truth not yet marked reviewed (a draft)")
    args = parser.parse_args()

    truth = json.loads(args.truth.read_text())
    report = evaluate(json.loads(args.output.read_text()), truth, args.include_unreviewed)
    if report.scored_sets == 0 and report.set_truth == 0:
        sys.exit(f"{args.truth}: nothing marked reviewed yet "
                 "(set \"reviewed\": true, or pass --include-unreviewed)")
    report.print()


if __name__ == "__main__":
    main()
