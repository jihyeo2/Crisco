from extract.codes import Legend, classify, parse_legend_rows
from extract.lines import Line
from extract.models import Component, HardwareSet
from extract.resolve import resolve_mfr_finish


# --- classification -----------------------------------------------------------

def test_seed_classifies_standard_codes():
    assert classify("626") == "finish"
    assert classify("613 (OIL RUBBED BRONZE)") == "finish"
    assert classify("US26D") == "finish"
    assert classify("IVE") == "mfr"
    assert classify("PEMKO / NGP / ZERO") == "mfr"
    assert classify("AA") == "ambiguous"
    assert classify("SA") == "unknown"   # 2-letter codes need the document's legend
    assert classify(None) == "unknown"


def test_document_legend_overrides_seed():
    legend = Legend(mfr={"PE": "Pemko", "SA": "Sargent"}, finish={"AL": "Aluminum"})
    assert classify("PE", legend) == "mfr"
    assert classify("SA", legend) == "mfr"
    assert classify("AL", legend) == "finish"


# --- legend parsing -----------------------------------------------------------

def test_parses_legend_across_page_noise_and_stops_at_next_subsection():
    rows = [
        ["B.", "Manufacturer’s Abbreviations:"],
        ["1.", "PE", "Pemko"],
        ["5.", "MED1 Medeco"],
        ["DOOR HARDWARE", "087100 - 16"],          # page footer
        ["MORRIS BANK", "SECTION 087100-17"],      # next page header
        ["6.", "SA", "Sargent"],
        ["C. Option List"],
        ["Code", "Description"],
        ["NRP", "Non-Removable Pin"],              # an option, not a manufacturer
        ["D. Hardware Finish List"],
        ["Code", "Description"],
        ["10BE", "Dark Oxidized Satin Bronze"],
    ]
    legend = parse_legend_rows(rows)
    assert legend.mfr == {"PE": "Pemko", "MED1": "Medeco", "SA": "Sargent"}
    assert legend.finish == {"10BE": "Dark Oxidized Satin Bronze"}


def test_prose_mentioning_abbreviations_is_not_a_heading():
    rows = [["2. Include abbreviations and symbols page to include manufacturers’ "
             "abbreviations, finish code descriptions"], ["NRP", "Non-Removable Pin"]]
    assert parse_legend_rows(rows) == Legend()


# --- column-position voting ----------------------------------------------------

def row(page, idx, y, cells):
    """One visual row of cells at the given x positions -> Lines."""
    return [Line(f"p{page}_L{idx + i:03d}", page, (x, y, x + 30, y + 10), text)
            for i, (x, text) in enumerate(cells)]


def comp(lines, mfr, finish, desc):
    return Component(qty=1, description=desc, mfr=mfr, finish=finish,
                     source_line_ids=[l.id for l in lines])


def hfh_like_set():
    """HFH layout: ... | finish (x=400) | mfr (x=450), no legend."""
    r1 = row(40, 1, 100, [(74, "HEAVYWEIGHT HINGE"), (400, "652"), (450, "IVE")])
    r2 = row(40, 4, 120, [(74, "SURFACE CLOSER"), (400, "689"), (450, "LCN")])
    r3 = row(40, 7, 140, [(74, "RAIN DRIP"), (200, "142AA"), (400, "AA"), (450, "ZER")])
    lines = r1 + r2 + r3
    comps = [comp(r1, "IVE", "652", "HEAVYWEIGHT HINGE"),
             comp(r2, "LCN", "689", "SURFACE CLOSER"),
             # the model put the ambiguous AA in mfr and ZER in finish
             comp(r3, "AA", "ZER", "RAIN DRIP")]
    return [HardwareSet(set_number="032", components=comps)], {l.id: l for l in lines}


def test_ambiguous_code_resolved_by_column_position():
    sets, by_id = hfh_like_set()
    sets, warnings = resolve_mfr_finish(sets, by_id, Legend())
    drip = sets[0].components[2]
    assert (drip.mfr, drip.finish) == ("ZER", "AA")
    assert drip.field_confidence == {"finish": 0.8}   # decided by position
    assert warnings


def test_unambiguous_swap_fixed_without_position():
    sets, by_id = hfh_like_set()
    closer = sets[0].components[1].model_copy(update={"mfr": "689", "finish": "LCN"})
    sets[0] = sets[0].model_copy(update={"components": [closer]})
    sets, _ = resolve_mfr_finish(sets, by_id, Legend())
    c = sets[0].components[0]
    assert (c.mfr, c.finish) == ("LCN", "689") and c.field_confidence == {}


def test_undecidable_value_kept_and_flagged():
    lines = row(40, 1, 100, [(74, "STOP"), (450, "XQ")])
    s = [HardwareSet(set_number="1", components=[comp(lines, "XQ", None, "STOP")])]
    s, _ = resolve_mfr_finish(s, {l.id: l for l in lines}, Legend())
    c = s[0].components[0]
    assert (c.mfr, c.finish) == ("XQ", None) and c.field_confidence == {"mfr": 0.5}


def test_values_sharing_one_line_use_character_position():
    # StarHardware prints "622 FH" in one cell: finish first, then mfr
    known = row(60, 1, 100, [(74, "Hinge"), (420, "622 IV")])
    odd = row(60, 3, 120, [(74, "Pivot"), (420, "622 FH")])
    comps = [comp(known, "IV", "622", "Hinge"), comp(odd, "622", "FH", "Pivot")]
    s = [HardwareSet(set_number="1", components=comps)]
    s, _ = resolve_mfr_finish(s, {l.id: l for l in known + odd}, Legend(mfr={"IV": "Ives"}))
    c = s[0].components[1]
    assert (c.mfr, c.finish) == ("FH", "622")
