# Voice Synthesizer

Prepare your emails to fine-tune a GPT model on your writing style.

## Quick Start

Run this in Terminal:

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
4. Choose **MBOX format**
5. Download and extract to get your `.mbox` file

## Two Modes

**Get started** — Drop your mbox, enter your email, done. Uses smart defaults.

**Get started (advanced)** — Walk through each setting with explanations:
- Date range (how far back to look)
- Emails per category (balances training data)
- Minimum email length (filters out "Thanks!" type emails)
- Duplicate threshold (how similar = duplicate)

## Resumes Automatically

If it crashes or you quit, just run it again. It remembers where you left off.

## Command Line

```bash
# Full pipeline
./voice-synth run "All mail.mbox" --sender you@gmail.com

# Individual stages
./voice-synth import "All mail.mbox" --out emails.json
./voice-synth convert emails.json --out emails.jsonl
./voice-synth clean emails.jsonl --sender you@example.com --years 5
./voice-synth curate cleaned_emails.json --per-topic 200 --dedupe-threshold 0.8
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
