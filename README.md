# Voice Synthesizer

Prepare your emails to fine-tune a GPT model on your writing style.

## Quick Start

Open Terminal (`Cmd + Space`, type "Terminal", hit Enter) and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/s-b-e-n-s-o-n/voice-synth/main/install.sh | bash
```

That's it. Everything installs automatically.

**Run again later:**

```bash
cd ~/voice-synth-main && ./voice-synth
```

**Update:** Just run the curl command again.

## What It Does

1. **Import** - Reads your Google Takeout MBOX, strips attachments
2. **Clean** - Filters to emails you sent in the last 5 years
3. **Anonymize** - Replaces names, emails, phones, addresses with `[PERSON]`, `[EMAIL]`, etc.
4. **Deduplicate** - Removes exact and near-duplicate emails
5. **Curate** - Picks the best examples across topics, outputs a CSV

**Output:** `~/Desktop/style_shortlist.csv` — open in a spreadsheet to review.

## Getting Your Emails

1. Go to [Google Takeout](https://takeout.google.com)
2. Click "Deselect all", then select only **Mail**
3. Click "All Mail data included" and pick labels (or keep all)
4. Choose **MBOX format**, file size **50 GB** (avoids splitting)
5. Download — you can point the tool at the `.zip` directly, or extract first

## Two Modes

**Get started** — Drop your mbox, enter your email, done. Uses smart defaults.

**Get started (advanced)** — Walk through each setting with explanations:
- Date range (how far back to look)
- Emails per category (balances training data)
- Minimum email length (filters out "Thanks!" type emails)
- Duplicate threshold (how similar = duplicate)

## Resumes Automatically

If it crashes or you quit, just run it again. It skips completed stages and picks up where it left off.

Use `--fresh` to force a full re-run from scratch.

## Command Line

```bash
# Full pipeline (accepts .zip, folder, or .mbox)
python pipeline.py run takeout.zip --sender you@gmail.com
python pipeline.py run ./Takeout/ --sender you@gmail.com
python pipeline.py run "All mail.mbox" --sender you@gmail.com

# With options
python pipeline.py run mail.mbox --sender you@gmail.com --fresh    # Force re-run
python pipeline.py run mail.mbox --sender you@gmail.com --verbose  # Show JSON details

# Individual stages
python pipeline.py import "All mail.mbox" --out emails.json
python pipeline.py convert emails.json --out emails.jsonl
python pipeline.py clean emails.jsonl --sender you@example.com --years 5
python pipeline.py curate cleaned_emails.json --per-topic 200 --dedupe-threshold 0.8
```

## Pipeline

```
MBOX → Import → Convert → Clean → Dedupe → Curate → CSV
```

| Stage | What it does |
|-------|--------------|
| Import | Parse MBOX, strip attachments |
| Convert | Stream to JSONL, filter fields |
| Clean | Filter by sender/date, remove auto-replies, anonymize PII |
| Dedupe | Remove exact matches (SHA-256) and near-duplicates (MinHash LSH) |
| Curate | Score by quality, balance across topics, output shortlist |

## PII Anonymization

Uses Microsoft Presidio (NLP-based, not just regex):

| Found | Replaced with |
|-------|---------------|
| Names | `[PERSON]` |
| Emails | `[EMAIL]` |
| Phones | `[PHONE]` |
| Addresses | `[LOCATION]` |
| Credit Cards | `[CREDIT_CARD]` |
| SSNs | `[SSN]` |
| IPs | `[IP]` |
| URLs | `[URL]` |

## Output

Final output: `~/Desktop/style_shortlist.csv`

| Column | Description |
|--------|-------------|
| subject | Email subject |
| body | Cleaned, anonymized body |
| topic | Category (client, strategy, update, feedback, workshop, other) |
| richness_score | Quality metric |

Open in a spreadsheet, review, then use for fine-tuning.

## Dependencies

Everything installs automatically to `~/.cache/voice-synth/`:
- gum (terminal UI)
- ijson (streaming JSON)
- presidio (PII detection)
- spacy + en_core_web_lg
- datasketch (deduplication)

**Reset:** `rm -rf ~/.cache/voice-synth`
