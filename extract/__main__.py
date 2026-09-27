"""CLI: python -m extract <pdf> -o out.json [--pages 28-46]"""

import argparse
import sys
from pathlib import Path

from extract.pipeline import run


def parse_pages(spec: str) -> list[int]:
    """'3-5,9' -> [3, 4, 5, 9]"""
    pages: list[int] = []
    for part in spec.split(","):
        start, _, end = part.strip().partition("-")
        pages.extend(range(int(start), int(end or start) + 1))
    return sorted(set(pages))


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract door hardware sets from a specbook PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True, help="JSON file to write")
    parser.add_argument("--pages", type=parse_pages,
                        help="pages to read, e.g. '28-46' or '3-5,9' (default: auto-select)")
    args = parser.parse_args()

    result, warnings, usage = run(args.pdf, pages=args.pages)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2))

    n_components = sum(len(s.components) for s in result.sets)
    print(f"{len(result.sets)} sets, {n_components} components -> {args.output}", file=sys.stderr)
    print(f"tokens: {usage.input_tokens} in / {usage.output_tokens} out, "
          f"cost ~${usage.cost_usd:.2f}", file=sys.stderr)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
