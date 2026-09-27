from extract.evaluate import evaluate, match_components, norm, norm_notes


def c(qty, desc, cat=None, mfr=None, finish=None):
    return {"qty": qty, "description": desc, "catalog_number": cat, "mfr": mfr, "finish": finish}


TRUTH = {
    "source_pdf": "x.pdf",
    "all_set_numbers_reviewed": True,
    "all_set_numbers": ["1.0", "2.0", "3.0"],
    "sets": [{
        "set_number": "1.0", "reviewed": True,
        "components": [c(None, "Hinge", "TA2714", "McKinney"),
                       c(1, "Closer", "4040XP", "LCN", "689"),
                       c(1, "Stop", "WS401", "IVES", "626")],
    }, {
        "set_number": "2.0", "reviewed": False,   # draft: not scored by default
        "components": [c(1, "Lock", "L9080", "SCHLAGE")],
    }],
}


def test_norm_ignores_case_spacing_and_quote_style():
    assert norm("R 7500/ PR7500") == norm("r 7500/PR7500")
    assert norm('4.5”') == norm('4.5"')
    assert norm(1) == norm(1.0) and norm("") is None


def test_matching_pairs_rows_by_content_not_order():
    truth = [c(1, "Closer", "4040XP"), c(1, "Stop", "WS401")]
    pred = [c(1, "Stop", "WS401"), c(1, "Closer", "4040XP")]
    pairs = {(t["description"], p["description"]) for t, p in match_components(truth, pred)}
    assert pairs == {("Closer", "Closer"), ("Stop", "Stop")}


def test_perfect_output_scores_full_marks():
    out = {"sets": [{"set_number": s, "components": comps} for s, comps in
                    [("1.0", TRUTH["sets"][0]["components"]), ("2.0", []), ("3.0", [])]]}
    r = evaluate(out, TRUTH)
    assert (r.set_found, r.set_truth, r.scored_sets) == (3, 3, 1)
    assert r.comp_matched == r.comp_truth == 3
    assert all(v == 3 for v in r.field_correct.values())
    assert r.qty_guessed == 0 and r.swapped == 0


def test_errors_are_counted():
    out = {"sets": [
        {"set_number": "1.0", "components": [
            c(3, "Hinge", "TA2714", "McKinney"),             # guessed qty
            c(1, "Closer", "4040XP", "689", "LCN"),           # mfr/finish swapped
        ]},                                                   # Stop missing
        {"set_number": "UNKNOWN", "components": []},
    ]}
    r = evaluate(out, TRUTH)
    assert r.missing_sets == ["2.0", "3.0"] and r.extra_sets == ["UNKNOWN"]
    assert (r.comp_matched, r.comp_truth) == (2, 3)
    assert r.qty_guessed == 1
    assert r.swapped == 1 and r.mfr_finish_correct == 1   # the hinge's mfr is right
    assert r.field_correct["qty"] == 1


def test_unreviewed_sets_only_scored_on_request():
    out = {"sets": [{"set_number": "2.0", "components": [c(1, "Lock", "L9080", "SCHLAGE")]}]}
    assert evaluate(out, TRUTH).scored_sets == 1
    r = evaluate(out, TRUTH, include_unreviewed=True)
    assert r.scored_sets == 2 and "UNREVIEWED" in r.label


def test_notes_scored_separately_from_main_accuracy():
    truth = {"source_pdf": "x.pdf", "sets": [{"set_number": "1", "reviewed": True, "components": [
        dict(c(1, "Stop", "RM860", "Rockwood"), notes="Per Conditions")]}]}
    out = {"sets": [{"set_number": "1", "components": [
        dict(c(1, "Stop", "RM860", "Rockwood"), notes="per conditions, see plans")]}]}
    r = evaluate(out, truth)
    assert (r.notes_correct, r.notes_total) == (0, 1)
    assert r.main_correct == 5            # all five main fields right despite the notes
    assert r.mismatches == [] and len(r.notes_mismatches) == 1


def test_notes_ignore_surrounding_parentheses_only():
    assert norm_notes("(as required)") == norm_notes("as required")
    assert norm_notes("(Cutouts as Required)") == norm_notes("Cutouts as Required")
    assert norm_notes("(BY OTHERS); PREP") != norm_notes("BY OTHERS; PREP")  # not wrapped
    assert norm_notes(None) is None
