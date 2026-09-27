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


def test_values_sharing_one_cell_are_separate_columns():
    # StarHardware prints "622 FH" in one cell: finish first, then mfr
    known = row(60, 1, 100, [(74, "Hinge"), (420, "622 IV")])
    odd = row(60, 3, 120, [(74, "Pivot"), (420, "622 FH")])
    comps = [comp(known, "IV", "622", "Hinge"), comp(odd, "622", "FH", "Pivot")]
    s = [HardwareSet(set_number="1", components=comps)]
    s, _ = resolve_mfr_finish(s, {l.id: l for l in known + odd}, Legend(mfr={"IV": "Ives"}))
    c = s[0].components[1]
    assert (c.mfr, c.finish) == ("FH", "622")


def test_column_context_overrides_the_value_itself():
    # PE printed in a column of 626/630 is a finish here (Painted Enamel)
    rows = [row(50, 1, 100, [(74, "Hinge"), (400, "626"), (450, "MK")]),
            row(50, 4, 120, [(74, "Closer"), (400, "630"), (450, "LCN")]),
            row(50, 7, 140, [(74, "Stop"), (400, "630"), (450, "RO")]),
            row(50, 10, 160, [(74, "Plate"), (400, "PE"), (450, "RO")])]
    comps = [comp(r, r[2].text, r[1].text, r[0].text) for r in rows]
    comps[3] = comps[3].model_copy(update={"mfr": "PE", "finish": "RO"})  # model's swap
    legend = Legend(mfr={"PE": "Pemko"})   # the legend says PE is Pemko...
    s, warnings = resolve_mfr_finish([HardwareSet(set_number="1", components=comps)],
                                     {l.id: l for r in rows for l in r}, legend)
    plate = s[0].components[3]
    assert (plate.mfr, plate.finish) == ("RO", "PE")   # ...but its column wins
    assert plate.field_confidence["finish"] == 0.6
    assert any("printed in the finish column" in w for w in warnings)


def test_unrecognized_column_inferred_as_the_other_kind():
    # no legend, 2-letter mfr codes: only the finish column has known codes
    rows = [row(50, 1, 100, [(74, "Hinge"), (400, "626"), (450, "MK")]),
            row(50, 4, 120, [(74, "Stop"), (400, "630"), (450, "RO")])]
    comps = [comp(rows[0], "626", "MK", "Hinge"),        # model swapped this one
             comp(rows[1], "RO", "630", "Stop")]
    s, _ = resolve_mfr_finish([HardwareSet(set_number="1", components=comps)],
                              {l.id: l for r in rows for l in r}, Legend())
    assert [(c.mfr, c.finish) for c in s[0].components] == [("MK", "626"), ("RO", "630")]


def test_stray_no_outside_any_column_is_not_forced():
    rows = [row(50, 1, 100, [(74, "Hinge"), (400, "626"), (450, "IVE")]),
            row(50, 4, 120, [(74, "Closer"), (400, "689"), (450, "LCN")]),
            row(50, 7, 140, [(74, "Stop"), (250, "NO"), (450, "IVE")])]
    comps = [comp(rows[0], "IVE", "626", "Hinge"), comp(rows[1], "LCN", "689", "Closer"),
             comp(rows[2], "IVE", "NO", "Stop")]
    s, _ = resolve_mfr_finish([HardwareSet(set_number="1", components=comps)],
                              {l.id: l for r in rows for l in r}, Legend())
    stop = s[0].components[2]
    assert (stop.mfr, stop.finish) == ("IVE", "NO") and stop.field_confidence == {"finish": 0.5}


def test_prose_column_is_not_inferred_as_the_other_kind():
    # JC Ryan set 3.0: "By Fire Rated Door Manufacturer" sits apart from the mfr
    # column; with only one labeled column it must not become a finish column.
    rows = [row(30, 1, 100, [(74, "Hinge"), (300, "By Fire Rated Door Manufacturer")]),
            row(30, 3, 120, [(74, "Gasketing"), (300, "By Fire Rated Door Manufacturer")]),
            row(30, 5, 140, [(74, "Exit Device"), (460, "Sargent")]),
            row(30, 7, 160, [(74, "Stop"), (460, "Rockwood")])]
    comps = [comp(rows[0], "By Fire Rated Door Manufacturer", None, "Hinge"),
             comp(rows[1], "By Fire Rated Door Manufacturer", None, "Gasketing"),
             comp(rows[2], "Sargent", None, "Exit Device"),
             comp(rows[3], "Rockwood", None, "Stop")]
    s, _ = resolve_mfr_finish([HardwareSet(set_number="3.0", components=comps)],
                              {l.id: l for r in rows for l in r}, Legend())
    hinge = s[0].components[0]
    assert hinge.finish is None and hinge.mfr == "By Fire Rated Door Manufacturer"
    assert hinge.field_confidence == {"mfr": 0.5}     # kept as the model had it, flagged
