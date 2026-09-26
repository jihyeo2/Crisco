from extract.recon import compress_ranges, count_hardware_hits


def test_keywords_match_common_forms():
    # Matches don't overlap: "HARDWARE SET" consumes SET, so "SET NO" isn't counted too.
    assert count_hardware_hits("HARDWARE SET NO. 3") == 1
    assert count_hardware_hits("Hw Set #12") == 1
    assert count_hardware_hits("Set: 3.0") == 1
    assert count_hardware_hits("DOOR HARDWARE SCHEDULE") == 1
    assert count_hardware_hits("Heading 04") == 1


def test_keywords_ignore_unrelated_words():
    assert count_hardware_hits("SETTING BEDS AND OFFSET HINGES") == 0
    assert count_hardware_hits("") == 0


def test_compress_ranges():
    assert compress_ranges([]) == "-"
    assert compress_ranges([7]) == "7"
    assert compress_ranges([3, 4, 5, 9, 11, 12]) == "3-5, 9, 11-12"
