"""Pick the pages that hold hardware sets and group them into LLM-sized chunks.

Usage (preview, no API calls):
    python -m extract.pages path/to/specbook.pdf
"""

import argparse
import re
from pathlib import Path

import pymupdf

# A set header starts a line and is followed by a set number:
#   "Set: 12.0", "Set #108", "Heading #4", "Hardware Group No. 09:",
#   "HARDWARE GROUP NO. C201CW", "Hardware Group/Set #02.1", "HW SET 3", "Set: EX-1.0",
#   "Hardware Groups/Set #10.1", "Hardware Group/Sets #102"
# The first letter must be a capital, so wrapped prose like `set 46" above floor`
# doesn't count; the rest is case-insensitive.
SET_HEADER = re.compile(
    r"^(?=[A-Z])(?i:(?:HARDWARE\s+|HW\.?\s*)?(?:GROUPS?\s*/\s*SETS?|SETS?|GROUPS?|HEADING)"
    r"\s*(?:NO\.?|NUMBER)?\s*[#:]?\s*[A-Z]{0,4}-?\d)",
    re.MULTILINE,
)
# Tabular schedules (e.g. Roselle) have no per-set header line, just a titled
# table with a standalone "SET" column header.
SCHEDULE_TITLE = re.compile(r"HARDWARE\s+SCHEDULE", re.IGNORECASE)
SET_COLUMN = re.compile(r"^\s*SET\s*$", re.IGNORECASE | re.MULTILINE)

CHUNK_PAGES = 4
# Dense tabular pages hold ~400 lines each; capping lines keeps each answer short
# enough to finish (a 1,200-line chunk overflowed the output limit). 900 still lets
# two dense pages share a chunk, so table rows that cross a page keep their set.
CHUNK_MAX_LINES = 900
CHUNK_OVERLAP = 1
# Header pages at most this many pages apart are treated as one block, so the
# pages between them (long sets, header-less continuation pages) are kept.
# Measured across 44 specbooks: gaps inside a set block are <=3 (e.g. HFH p121-122,
# a blank page then a header-less continuation); the smallest gap between
# unrelated hits is 9. Any value 3-8 selects the same pages; 3 is the most
# conservative.
MAX_GAP = 3


def is_hardware_page(text: str) -> bool:
    if SET_HEADER.search(text):
        return True
    return bool(SCHEDULE_TITLE.search(text) and SET_COLUMN.search(text))


def expand_hits(hits: list[int], page_count: int, max_gap: int = MAX_GAP) -> list[int]:
    """Fill gaps of up to `max_gap` pages between header pages, then add the page
    after each block so the block's last set can run onto it."""
    selected: set[int] = set()
    hits = sorted(hits)
    for prev, nxt in zip(hits, hits[1:]):
        if nxt - prev - 1 <= max_gap:
            selected.update(range(prev, nxt))
    for p in hits:
        selected.add(p)
        if p < page_count:
            selected.add(p + 1)
    return sorted(selected)


def select_pages(doc: pymupdf.Document) -> list[int]:
    """1-based pages that hold (part of) a hardware set."""
    hits = [page.number + 1 for page in doc if is_hardware_page(page.get_text())]
    return expand_hits(hits, doc.page_count)


def chunk_pages(pages: list[int], line_counts: dict[int, int] | None = None,
                size: int = CHUNK_PAGES, max_lines: int = CHUNK_MAX_LINES,
                overlap: int = CHUNK_OVERLAP) -> list[list[int]]:
    """Split consecutive runs of pages into chunks of at most `size` pages and
    `max_lines` text lines (a single page over the limit still gets its own chunk).

    Within a run, neighbouring chunks share `overlap` page(s) so a set crossing a
    chunk boundary is seen whole at least once; duplicates are merged later.
    Separate runs never share a chunk.
    """
    counts = line_counts or {}
    runs: list[list[int]] = []
    for p in pages:
        if runs and p == runs[-1][-1] + 1:
            runs[-1].append(p)
        else:
            runs.append([p])

    chunks = []
    for run in runs:
        start = 0
        while True:
            end, lines = start, 0
            while end < len(run) and end - start < size:
                lines += counts.get(run[end], 0)
                if end > start and lines > max_lines:
                    break
                end += 1
            chunks.append(run[start:end])
            if end >= len(run):
                break
            # step back for overlap, but always move forward
            start = max(end - overlap, start + 1)
    return chunks


def main() -> None:
    from extract.recon import compress_ranges

    parser = argparse.ArgumentParser(description="Preview page selection and chunks.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    with pymupdf.open(args.pdf) as doc:
        pages = select_pages(doc)
        chunks = chunk_pages(pages)
        print(f"{args.pdf}: {doc.page_count} pages")
        print(f"  selected {len(pages)}: {compress_ranges(pages)}")
        print(f"  {len(chunks)} chunks: " + "  ".join(compress_ranges(c) for c in chunks))


if __name__ == "__main__":
    main()
