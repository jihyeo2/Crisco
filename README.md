# Crisco

Extracts door hardware sets from construction specbook PDFs.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

Put specbook PDFs under `specbooks/` (not committed).
