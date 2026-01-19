# Voice Synth

Turn your emails into training data for a GPT that writes like you.

## Quick Start

Open Terminal and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/s-b-e-n-s-o-n/voice-synth/main/install.sh | bash
```

That's it. The TUI guides you through everything.

**Run again later:**
```bash
~/voice-synth/voice-synth-tui
```

## What You'll Need

Your emails from Google Takeout:

1. Go to [takeout.google.com](https://takeout.google.com)
2. Click "Deselect all", then select only **Mail**
3. Download (any size - we handle split exports)

## What It Does

1. **Imports** your mbox (filters spam/trash/drafts, emails older than 5 years)
2. **Converts** to processing format
3. **Cleans & Anonymizes** - filters to emails you sent, replaces PII
4. **Curates** the best examples across topics, removes duplicates

**Output:** `~/Desktop/style_shortlist.csv`

## Features

- **Visual TUI** - Progress bars, stage tracking, live output
- **Auto-resume** - Quit anytime, pick up where you left off
- **Auto-detect** - Finds your email address from the mbox
- **Drag & drop** - Drop files from Finder into the terminal

## Privacy

All processing happens locally. Nothing leaves your machine.

PII is replaced using Microsoft Presidio (NLP-based detection):
- Names → `[PERSON]`
- Emails → `[EMAIL]`
- Phones → `[PHONE]`
- Addresses → `[LOCATION]`
- Credit cards, SSNs, IPs, URLs → anonymized

## Command Line

Skip the TUI and run directly:

```bash
cd ~/voice-synth

# Full pipeline
~/.cache/voice-synth/venv/bin/python pipeline.py run takeout.mbox --sender you@gmail.com

# Individual stages
~/.cache/voice-synth/venv/bin/python pipeline.py import mail.mbox --out emails.json
~/.cache/voice-synth/venv/bin/python pipeline.py convert emails.json --out emails.jsonl
~/.cache/voice-synth/venv/bin/python pipeline.py clean emails.jsonl --out cleaned.json --sender you@gmail.com
~/.cache/voice-synth/venv/bin/python pipeline.py curate cleaned.json --out shortlist.csv
```

## Uninstall

From the TUI menu, select "Uninstall" and type `uninstall` to confirm.

Or manually:
```bash
rm -rf ~/voice-synth ~/.cache/voice-synth
```

## Requirements

- macOS (ARM64) - Intel/Linux users can build from source
- Python 3.9+

## Building from Source

```bash
# Install Go 1.21+
go build -o voice-synth-tui .

# Dependencies installed automatically on first run
```
