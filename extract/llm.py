"""Ask Claude to read hardware sets out of a chunk of ID'd lines.

The model sees lines as `p40_L012  x=74 y=184  1 Surface Closer` and answers in a
strict JSON schema that holds values and line IDs only, never coordinates.
"""

from dataclasses import dataclass
from typing import Literal

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from extract.lines import Line, format_for_prompt

MODEL = "claude-sonnet-5"
# USD per million tokens for MODEL, used for the cost line in run summaries.
PRICE_PER_MTOK = {"input": 2.00, "output": 10.00}
# Thinking depth / token spend. Tune against the eval (step 5).
EFFORT = "medium"
# Dense tabular schedules produce long answers (a 3-page table overflowed 16k), so
# stream with a high ceiling; streaming avoids HTTP timeouts on long outputs.
MAX_TOKENS = 64000

SYSTEM_PROMPT = """\
You extract door hardware sets from construction specification pages for estimators.

Input: the text lines of a few consecutive pages. Each line is
`<line_id>  x=<left> y=<top>  <text>`. x/y are PDF points (origin top-left); use them
to rebuild table columns and rows, since table cells arrive as separate lines.

A hardware set (also "hardware group" or "heading") has a set number, an optional
description, and a list of components. Each component is one row: quantity, item
description, catalog/model number, manufacturer, finish, notes.

Rules:
- Only report what is printed. Never invent or normalize values; copy text as written.
- qty: the number printed for that row. If no quantity is printed (blank, "_", "--",
  "as required"), use null. Never infer a quantity. Units like "EA" or "PR" are not
  part of qty; keep "PR"/pair info in notes.
- A set marked NOT USED / DELETED / OMITTED / VOID is still reported, with
  status "not_used", plus any components still printed under it.
- mfr is the manufacturer name or abbreviation (e.g. IVE, LCN, Norton); finish is the
  finish code (e.g. 626, 630, US26D, 689). If you can't tell which is which, still
  assign your best guess and list both fields in low_confidence_fields.
- line_ids: every line a value came from. header_line_ids: lines for the set number,
  description, and any NOT USED marker. Use only IDs that appear in the input.
- Pages may start or end mid-set. Report partial sets with the set number if it is
  visible; if a page starts with components whose set header is not in the input,
  use set_number "UNKNOWN".
- Door lists, operational descriptions, and general notes are not components; put
  set-level text that matters into the set description only if it describes the set.
- If the pages contain no hardware sets, return an empty list.
- confidence: 0-1 for the set as a whole (lower if the layout was hard to read or the
  set is cut off).
"""


class LLMComponent(BaseModel):
    qty: float | None
    description: str
    catalog_number: str | None
    mfr: str | None
    finish: str | None
    notes: str | None
    line_ids: list[str]
    low_confidence_fields: list[
        Literal["qty", "description", "catalog_number", "mfr", "finish", "notes"]
    ]


class LLMSet(BaseModel):
    set_number: str
    description: str | None
    status: Literal["active", "not_used"]
    header_line_ids: list[str]
    components: list[LLMComponent]
    confidence: float


class LLMChunkResult(BaseModel):
    sets: list[LLMSet]


class ExtractionError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens,
                     self.output_tokens + other.output_tokens)

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens * PRICE_PER_MTOK["input"]
                + self.output_tokens * PRICE_PER_MTOK["output"]) / 1e6


def make_client() -> anthropic.Anthropic:
    load_dotenv()
    return anthropic.Anthropic()


def extract_chunk(client: anthropic.Anthropic, lines: list[Line]) -> tuple[LLMChunkResult, Usage]:
    where = f"pages {lines[0].page}-{lines[-1].page}"
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={"effort": EFFORT},
            messages=[{"role": "user", "content": format_for_prompt(lines)}],
            output_format=LLMChunkResult,
        ) as stream:
            response = stream.get_final_message()
    except ValidationError as e:
        # The SDK parses the JSON as the text block closes; a cut-off answer lands here.
        raise ExtractionError(f"invalid/truncated JSON for {where}: {e.errors()[0]['msg']}") from e
    where += f" (message {response.id})"
    if response.stop_reason == "refusal":
        raise ExtractionError(f"model refused {where}")
    if response.stop_reason == "max_tokens":
        raise ExtractionError(f"output hit max_tokens={MAX_TOKENS} on {where}; use smaller chunks")
    usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
    return response.parsed_output, usage


def count_chunk_tokens(client: anthropic.Anthropic, lines: list[Line]) -> int:
    """Input tokens for one chunk (free endpoint, used for cost previews)."""
    return client.messages.count_tokens(
        model=MODEL,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": format_for_prompt(lines)}],
    ).input_tokens
