# Example outputs

Pipeline outputs you can open in the viewer without an API key:

```bash
streamlit run viewer/app.py   # pick one under examples/
```

The viewer renders the source page, so put the specbook PDFs under `specbooks/`
with their original folder names (each JSON's `source_pdf` gives the path).

| File | Specbook | Format | Sets |
|---|---|---|---|
| `jcryan.json` | JC Ryan 2, 087100 Door Hardware | stacked list | 38 |
| `roselle.json` | Roselle Public Library, 087100 | table | 33 |
| `national_doors.json` | National Doors, FS17 specs (held-out eval) | short codes, no legend | 15 |
| `lyons.json` | Lyons Township HS | short codes, 4 NOT USED groups | 29 |
| `vantage_389-392.json` | Vantage TX-22, p389-392 only | `PART n - HARDWARE GROUP` | 9 |

All were produced by `python -m extract` with the final prompt. One exception:
`jcryan.json` set 3.0 comes from a rerun of page 30 (`--pages 30`), because the full
JC Ryan run predates the fix that stopped "By Fire Rated Door Manufacturer" being
read as a finish.
