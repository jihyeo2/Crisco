"""Recon: find where hardware sets live in each specbook before building the pipeline.

For every page we record how much text it has (near-zero means scanned/image-only)
and whether it matches hardware-set keywords. Matching pages get a low-DPI PNG
thumbnail under recon/ so a human can eyeball the layouts.

Usage:
    python -m extract.recon                      # every PDF under specbooks/
    python -m extract.recon path/a.pdf path/b.pdf
"""

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

SPECBOOKS_DIR = Path("specbooks")
RECON_DIR = Path("recon")

# A page with fewer characters than this is treated as scanned (image-only).
SCANNED_CHAR_THRESHOLD = 50
THUMBNAIL_DPI = 50

HARDWARE_PATTERN = re.compile(
    r"\bHARDWARE\s+SET\b"
    r"|\bHW\.?\s*SET\b"
    r"|\bSET\s*#"
    r"|\bSET\s+NO\b"
    r"|\bSET\s*:\s*\d"            # "Set: 3.0"
    r"|\bHARDWARE\s+SCHEDULE\b"
    r"|\bHARDWARE\s+GROUP\b"
    r"|\bHEADING\b",
    re.IGNORECASE,
)


@dataclass
class PdfReport:
    path: Path
    page_count: int = 0
    scanned_pages: list[int] = field(default_factory=list)
    # 1-based page number -> number of keyword matches on that page
    hit_pages: dict[int, int] = field(default_factory=dict)


def count_hardware_hits(text: str) -> int:
    return len(HARDWARE_PATTERN.findall(text))


def compress_ranges(pages: list[int]) -> str:
    """[3, 4, 5, 9, 11, 12] -> '3-5, 9, 11-12'"""
    if not pages:
        return "-"
    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def thumbnail_dir(pdf_path: Path) -> Path:
    # recon/<specbook folder>/<pdf stem>/ keeps multi-PDF specbooks apart
    return RECON_DIR / pdf_path.parent.name / pdf_path.stem


def scan_pdf(pdf_path: Path, save_thumbnails: bool = True) -> PdfReport:
    report = PdfReport(path=pdf_path)
    out_dir = thumbnail_dir(pdf_path)

    with pymupdf.open(pdf_path) as doc:
        report.page_count = doc.page_count
        for page in doc:
            page_no = page.number + 1
            text = page.get_text()

            if len(text.strip()) < SCANNED_CHAR_THRESHOLD:
                report.scanned_pages.append(page_no)

            hits = count_hardware_hits(text)
            if hits:
                report.hit_pages[page_no] = hits
                if save_thumbnails:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    page.get_pixmap(dpi=THUMBNAIL_DPI).save(out_dir / f"p{page_no:04d}.png")

    return report


def print_summary(report: PdfReport) -> None:
    hit_list = sorted(report.hit_pages)
    top = sorted(report.hit_pages.items(), key=lambda kv: -kv[1])[:3]
    print(f"\n{report.path}")
    print(f"  pages: {report.page_count}   scanned: {len(report.scanned_pages)}   "
          f"keyword pages: {len(hit_list)}")
    print(f"  keyword page ranges: {compress_ranges(hit_list)}")
    if top:
        print("  densest pages: " + ", ".join(f"p{p} ({n} hits)" for p, n in top))
    if report.scanned_pages:
        print(f"  scanned page ranges: {compress_ranges(report.scanned_pages)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdfs", nargs="*", type=Path,
                        help="PDFs to scan (default: all under specbooks/)")
    parser.add_argument("--no-thumbnails", action="store_true")
    args = parser.parse_args()

    pdfs = args.pdfs or sorted(SPECBOOKS_DIR.rglob("*.pdf"))
    for pdf in pdfs:
        print_summary(scan_pdf(pdf, save_thumbnails=not args.no_thumbnails))


if __name__ == "__main__":
    main()
