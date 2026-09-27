import pytest

from extract.lines import Line, format_for_prompt, line_id
from extract.pages import chunk_pages, expand_hits, is_hardware_page


@pytest.mark.parametrize("header", [
    "Set: 12.0",
    "Set #108",
    "Heading #4",
    "Hardware Group No. 09: (Doors 103A & 111A 114)",
    "HARDWARE GROUP NO. 05",
    "Hardware Group No. C201CW",
    "Hardware Group/Set #02.1",
    "HW SET 3",
    "Set: EX-1.0",
    "Hardware Groups/Set #10.1",
    "Hardware Group/Sets #102",
])
def test_set_headers_select_page(header):
    assert is_hardware_page(f"DOOR HARDWARE\n{header}\n1 Surface Closer")


@pytest.mark.parametrize("text", [
    "GASKETING SET\n188SB",
    "1 Lockset\nND80PD",
    "in accordance with the hardware schedule and templates",
    "PART 2 - PRODUCTS (Not Used)",
    "Set frames plumb and square",
    'Receptacles serving water coolers shall be\nset 46" above floor.',
])
def test_non_headers_do_not_select_page(text):
    assert not is_hardware_page(text)


def test_tabular_schedule_selects_page():
    assert is_hardware_page("DOOR HARDWARE SCHEDULE\nSET\nHARDWARE TYPE\n3.3\nMORTISE HINGE")


def test_expand_fills_small_gaps_and_adds_next_page():
    # 120 and 123 are header pages; 121-122 hold a long set's continuation
    assert expand_hits([120, 123], page_count=200, max_gap=3) == [120, 121, 122, 123, 124]
    # gap of 3 blank pages still bridged
    assert expand_hits([163, 167], page_count=200, max_gap=3) == [163, 164, 165, 166, 167, 168]


def test_expand_keeps_distant_blocks_separate():
    assert expand_hits([10, 50], page_count=200, max_gap=3) == [10, 11, 50, 51]


def test_expand_does_not_run_past_last_page():
    assert expand_hits([5], page_count=5) == [5]


def test_chunks_respect_size_overlap_and_runs():
    assert chunk_pages([28, 29, 30, 31, 32, 33, 34], size=4, overlap=1) == [
        [28, 29, 30, 31], [31, 32, 33, 34]]
    # separate runs never share a chunk
    assert chunk_pages([3, 4, 10, 11], size=4, overlap=1) == [[3, 4], [10, 11]]
    assert chunk_pages([], size=4, overlap=1) == []


def test_chunks_respect_line_budget():
    dense = {15: 384, 16: 428, 17: 381}
    assert chunk_pages([15, 16, 17], dense, max_lines=800) == [[15], [16], [17]]
    assert chunk_pages([15, 16, 17], dense, max_lines=900) == [[15, 16], [16, 17]]
    # one oversized page still gets a chunk, and chunking always moves forward
    assert chunk_pages([5, 6], {5: 2000, 6: 10}, max_lines=800) == [[5], [6]]


def test_line_ids_and_prompt_format_groups_rows():
    assert line_id(40, 12) == "p40_L012"
    lines = [Line("p16_L002", 16, (200.0, 184.5, 260.0, 195.0), "IVES - 5BB1"),
             Line("p16_L001", 16, (74.0, 184.0, 150.0, 195.0), "MORTISE HINGE"),
             Line("p16_L003", 16, (74.0, 200.0, 150.0, 211.0), "WALL STOP"),
             Line("p17_L001", 17, (74.0, 90.0, 152.0, 101.0), "1 Stop")]
    assert format_for_prompt(lines) == (
        "=== PAGE 16 ===\n"
        "[p16_L001 x=74] MORTISE HINGE | [p16_L002 x=200] IVES - 5BB1\n"
        "[p16_L003 x=74] WALL STOP\n"
        "=== PAGE 17 ===\n"
        "[p17_L001 x=74] 1 Stop")
