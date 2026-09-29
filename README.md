# Crisco

Extracts door hardware sets from construction specbook PDFs: every set with its
components (qty, description, catalog number, manufacturer, finish, notes), where
it sits on the page, and how confident the extraction is. A Streamlit viewer shows
each set on the page and lets a reviewer correct it before exporting JSON.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

Put specbook PDFs under `specbooks/` (not committed).

## Usage

```bash
python -m extract <pdf> -o out/result.json          # extract (calls Claude)
python -m extract <pdf> -o out/r.json --pages 28-46 # limit to pages
streamlit run viewer/app.py                         # review, edit, export (examples/ included)
python -m extract.evaluate out/r.json eval/ground_truth/jcryan.json   # score
python -m extract.pages <pdf>                       # preview page selection (free)
python -m extract.recon                             # scan all specbooks (free)
pytest
```

The CLI prints token usage and an estimated cost for each run.

No API key? `examples/` holds finished outputs for five specbooks, so the viewer
works straight away; it only needs the specbook PDFs under `specbooks/` to render
pages (see `examples/README.md`).

## How it works

```
PDF ─► select pages ─► lines with IDs ─► chunks ─► Claude ─► assemble ─► mfr/finish ─► JSON
```

1. **Select pages** (`extract/pages.py`). Pages with a set header line (`Set: 12.0`,
   `Set #108`, `Heading #4`, `Hardware Group No. 09`, ...) or a titled schedule table.
   Gaps of up to 3 pages between header pages are filled (measured across 44
   specbooks) and the page after each block is added, so long sets keep their
   continuation pages. A 3,900-page manual becomes ~130 pages.
2. **Lines with IDs** (`extract/lines.py`). Every text line gets a stable ID like
   `p40_L012` and its bbox. Lines on the same visual row are grouped before prompting,
   so table cells arrive together.
3. **Chunks.** At most 4 pages and 900 lines, overlapping by one page so a set that
   crosses a boundary is seen whole at least once. Chunks run 4 at a time.
4. **Claude** (`extract/llm.py`). Sonnet 5, streamed, with a strict JSON schema of
   values and **line IDs only, never coordinates**.
5. **Assemble** (`extract/assemble.py`). Unknown line IDs are dropped; a qty that isn't
   printed in the component's own lines becomes null; one bbox per page is computed
   from line IDs; sets seen in overlapping chunks are merged; a catalog number that
   repeats the manufacturer ("IVES - 5BB1") loses the prefix.
6. **Manufacturer vs finish** (`extract/codes.py`, `extract/resolve.py`). Decided by
   the **column** a value is printed in, not by the value alone. Columns are labeled
   by majority vote of their values, classified with the document's own legend
   ("Manufacturer's Abbreviations", "Hardware Finish List") and a small seed of
   industry-standard codes. `PE` printed in a finish column is a finish, even though
   it's Pemko elsewhere. Only the PDF being processed is used.

### Rules the output follows

- **Missing quantities are null, never guessed.** Blank, `_`, `--` and "as required"
  are null, and any qty not printed in the row's own lines is set to null.
- **NOT USED sets are kept**, with `status: "not_used"`, plus any components still
  printed under them. They should never be priced.
- **No invented data or coordinates.** Values are copied as printed; every bbox comes
  from the line IDs the model cited.
- Uncertain fields are flagged in `field_confidence` (0.5: nothing could decide it;
  0.6-0.8: decided from context). The viewer lists them in a *check* column.

## Output

`ExtractionResult` in `extract/models.py`:

```json
{"source_pdf": "specbooks/...pdf",
 "sets": [{"set_number": "12.0", "description": "Passage function with closer - single",
           "status": "active",
           "locations": [{"page": 40, "bbox": [74.3, 111.7, 509.4, 250.4]}],
           "source_line_ids": ["p40_L010", "p40_L011"],
           "confidence": 0.9,
           "components": [{"qty": 1.0, "description": "Passage Latch",
                           "catalog_number": "8215 LNMI", "mfr": "Sargent",
                           "finish": null, "notes": null,
                           "source_line_ids": ["p40_L015", "p40_L016", "p40_L017"],
                           "field_confidence": {}}]}]}
```

Bboxes are PDF points, origin top-left, one per page the set appears on.

## Evaluation

Ground truth in `eval/ground_truth/` is hand-reviewed against the PDFs: sets picked
for tricky cases (page-crossing sets, missing quantities, empty sets, table
layouts), plus each specbook's full list of set numbers. Results are in
`eval/results/`.

| Main accuracy (qty, description, catalog, mfr, finish) | Baseline | Final |
|---|---|---|
| JC Ryan: stacked list, 9 sets / 47 rows | 95% | **100%** |
| Roselle: table, 8 sets / 45 rows | 89% | **99%** |
| **National Doors: held out, 4 sets / 21 rows** | — | **99%** |

Across all three: every set number found with no extras, and qty/mfr/finish 100%.
None of the 24 blank quantities in JC Ryan and Roselle was guessed. The held-out specbook was not used to write the prompt rules
or the code seed, and uses short codes (`630 | IVE`, `626 | ADA`) with no legend.

### Other runs (no ground truth, spot-checked against the PDF)

| Specbook | Sets found | Checked | Cost |
|---|---|---|---|
| Lyons Township HS, 11 pages | 29 / 29 headers | all 4 **NOT USED** groups (05, 16, 21, 22) came out `not_used`; group 07 matches the PDF row for row | $0.43 |
| Vantage TX-22, p389-392 | 9 / 9 headers | `PART 10 - HARDWARE GROUP NO. 103A` format; group 103A rows match except one (see limits) | $0.15 |

### Coverage across the corpus

Extracting every specbook wasn't in budget, so coverage was checked for free: for
each specbook, page selection was compared with recon's keyword pages, and every
dense run of keyword pages that selection skipped was read. That found one real miss,
Vantage's `PART 18 - HARDWARE GROUP NO. 201C` headers (~30 pages), now fixed; the
other skipped runs are submittal prose about the schedule.

| Specbook | Pages selected | Set headers found* | Extracted |
|---|---|---|---|
| JC Ryan 087100 | 23 | 38 | 38/38 |
| Roselle 087100 (table) | 3 | table, no headers | 33/33 |
| National Doors | 8 | 15 | 15/15 |
| Lyons Township HS | 11 | 29 | 29/29 |
| Vantage TX-22 | 34 | 44 | 9/9 on p389-392 |
| Gerrard (Hdw Spec & Sch) | 18 | 34 | — |
| Bridgeport Hardware Schedule | 47 | 90 | — |
| AMI Renovation | 24 | 44 | — |
| HFH 08 71 00 | 165 | 190 | p40-42 only |
| Livelle Vol 1 | 61 | 161 | — |
| Morris Bank | 40 | 47 | p283-285 only |
| SAT TDP | 133 | 181 | — |
| StarHardware | 63 | 69 | — |
| Valor Acres 087100 | 12 | 37 | — |
| Village of Oswego | 29 | 39 | — |
| Market View | 14 | 26 | — |
| Forest Park | 4 | 1 real (`Set #1`) | — |
| Shubie Center | 3 | 3 | — |
| USI Radnet | 5 | 3 | — |

\* Distinct header lines matched on the selected pages: an approximation, since a few
matches are bolt-grade text ("Group 1 stainless-steel bolts") rather than sets.
Not listed: SJC and Woodridge (no hardware sets), Bridgeport Rev_0 and Gerrard's
architectural specs (duplicates of files above), HFH's door index (door → set
numbers only), and door/frame/glazing sections (no sets).

## Cost

Sonnet 5 ($2 / $10 per million tokens). A hardware section costs roughly
$0.30-0.90: JC Ryan (23 pages) $0.78, Roselle (3 dense table pages) $0.89,
National Doors (8 pages) $0.28, Lyons (11 pages) $0.43. Most output tokens are the model's reasoning;
`EFFORT = "low"` in `extract/llm.py` is the next lever to try, measured with the eval.

## Known limits

- **Scanned pages aren't read** (no OCR), e.g. Bridgeport Rev_0 p50-238.
- **Instructions printed in the catalog column** can stay in catalog_number instead of
  notes: National Doors `BY GATE MFG`, Vantage `COORDINATE WITH OWNER`. No prompt rule
  covers them yet.
- A door list can end up as the set description (Lyons group 29: "For use on Door #(s):
  S8-1").
- Only 5 specbooks have been extracted (API budget); the rest are covered by the free
  header count above. Bolt-grade text ("Group 1 stainless-steel bolts") also matches
  the header pattern and selects a few extra pages, which costs a little; whether those
  pages produce false sets hasn't been checked.
- **Not fully consistent across chunks:** Roselle's second chunk left "(BY OTHERS)" in
  the catalog where the first moved it to notes.
- The last set of a block can lose rows if it runs more than one page past its header
  onto pages with no header.
- Sets are merged by number only when they're on the same or adjacent pages; a spec
  that prints its hardware section twice (Morris Bank) yields both copies.
- Confidence scores come from the model and aren't calibrated.
- The eval is small (21 sets). The prompt rules were written from JC Ryan and Roselle
  errors, which is why the held-out result matters most.
- The printed cost excludes failed attempts, which return no usage.
- Finish codes aren't pulled out of catalog numbers: on a kick plate `4BE` means four
  beveled edges.

## Layout

```
extract/   pipeline: recon, pages, lines, llm, assemble, codes, resolve, models, evaluate
viewer/    Streamlit review app (app.py) and its tested helpers (render.py)
eval/      ground truth and recorded results
examples/  finished outputs for the viewer (no API key needed)
tests/     pytest suite
```
