"""PDF -> ExtractionResult: select pages, chunk, ask Claude per chunk, assemble."""

import sys
from pathlib import Path

import pymupdf

from extract.assemble import assemble
from extract.lines import extract_lines
from extract.llm import extract_chunk, make_client
from extract.models import ExtractionResult
from extract.pages import chunk_pages, select_pages


def run(pdf_path: Path, pages: list[int] | None = None,
        log=lambda msg: print(msg, file=sys.stderr)) -> tuple[ExtractionResult, list[str]]:
    """Extract hardware sets. `pages` overrides automatic page selection."""
    client = make_client()
    with pymupdf.open(pdf_path) as doc:
        selected = pages or select_pages(doc)
        chunks = chunk_pages(selected)
        log(f"{pdf_path.name}: {len(selected)} pages in {len(chunks)} chunks")

        results = []
        for n, chunk in enumerate(chunks, 1):
            lines = extract_lines(doc, chunk)
            if not lines:
                continue
            log(f"  chunk {n}/{len(chunks)}: pages {chunk[0]}-{chunk[-1]} ({len(lines)} lines)")
            results.append((lines, extract_chunk(client, lines)))

    sets, warnings = assemble(results)
    return ExtractionResult(source_pdf=str(pdf_path), sets=sets), warnings
