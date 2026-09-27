"""PDF -> ExtractionResult: select pages, chunk, ask Claude per chunk, assemble."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

from extract.assemble import assemble
from extract.codes import find_legend
from extract.lines import Line, extract_page_lines
from extract.llm import ExtractionError, LLMChunkResult, Usage, extract_chunk, make_client
from extract.models import ExtractionResult
from extract.pages import chunk_pages, select_pages
from extract.resolve import resolve_mfr_finish

# Chunks sent to the API at once. The SDK retries rate limits (429) itself.
MAX_PARALLEL = 4


def run(pdf_path: Path, pages: list[int] | None = None,
        log=lambda msg: print(msg, file=sys.stderr)) -> tuple[ExtractionResult, list[str], Usage]:
    """Extract hardware sets. `pages` overrides automatic page selection."""
    client = make_client()
    with pymupdf.open(pdf_path) as doc:
        selected = pages or select_pages(doc)
        lines_by_page = {p: extract_page_lines(doc[p - 1]) for p in selected}
        legend = find_legend(doc, selected)
    if legend.mfr or legend.finish:
        log(f"legend: {len(legend.mfr)} mfr codes, {len(legend.finish)} finish codes")
    counts = {p: len(ls) for p, ls in lines_by_page.items()}
    chunks = [c for c in chunk_pages(selected, counts) if any(counts[p] for p in c)]
    log(f"{pdf_path.name}: {len(selected)} pages in {len(chunks)} chunks")

    failures: list[str] = []

    def call(chunk: list[int]) -> list[tuple[list[Line], LLMChunkResult, Usage]]:
        lines = [line for p in chunk for line in lines_by_page[p]]
        try:
            answer, usage = extract_chunk(client, lines)
        except ExtractionError as e:
            if len(chunk) == 1:
                failures.append(str(e))
                log(f"  FAILED {e}")
                return []
            # Too much for one answer: retry page by page (loses the overlap context).
            log(f"  pages {chunk[0]}-{chunk[-1]} failed ({e}); retrying one page at a time")
            return [r for p in chunk for r in call([p])]
        log(f"  pages {chunk[0]}-{chunk[-1]}: {len(answer.sets)} sets "
            f"({usage.input_tokens} in / {usage.output_tokens} out tokens)")
        return [(lines, answer, usage)]

    # map() keeps chunk order, which assembly relies on.
    with ThreadPoolExecutor(MAX_PARALLEL) as pool:
        results = [r for rs in pool.map(call, chunks) for r in rs]

    total = sum((usage for *_, usage in results), Usage())
    sets, warnings = assemble([(lines, answer) for lines, answer, _ in results])
    by_id = {line.id: line for ls in lines_by_page.values() for line in ls}
    sets, resolve_warnings = resolve_mfr_finish(sets, by_id, legend)
    warnings = [f"chunk failed: {f}" for f in failures] + warnings + resolve_warnings
    return ExtractionResult(source_pdf=str(pdf_path), sets=sets), warnings, total
