# Voice Synth

Turn your emails into training data for a GPT that writes like you.

## Quick Start

Open Terminal (`Cmd + Space`, type "Terminal", hit Enter) and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/s-b-e-n-s-o-n/voice-synth/main/install.sh | bash
```

That's it. Follow the prompts.

**Run again later:**
```bash
cd ~/voice-synth-main && ./voice-synth
```

**Update:** Just run the curl command again.

## What You'll Need

Your emails from Google Takeout:

1. Go to [takeout.google.com](https://takeout.google.com)
2. Click "Deselect all", then select only **Mail**
3. Download (any file size works - we handle split exports)

## What It Does

1. **Imports** your mbox (auto-detects your email, filters spam/trash/drafts)
2. **Cleans** to just emails you sent in the last 5 years
3. **Anonymizes** names, emails, phones, addresses → `[PERSON]`, `[EMAIL]`, etc.
4. **Dedupes** exact and near-duplicate emails
5. **Curates** the best examples across topics

**Output:** `~/Desktop/style_shortlist.csv`

## Resumes Automatically

Quit anytime. Run it again and it picks up where it left off.

## Command Line

```bash
# Full pipeline
python pipeline.py run takeout.mbox --sender you@gmail.com

# Accepts .zip, folder, or .mbox
python pipeline.py run takeout.zip --sender you@gmail.com
python pipeline.py run ./Takeout/ --sender you@gmail.com

# Force fresh run
python pipeline.py run mail.mbox --sender you@gmail.com --fresh
```

## Privacy

All processing happens locally. Nothing leaves your machine.

PII is replaced using Microsoft Presidio (NLP-based detection):
- Names → `[PERSON]`
- Emails → `[EMAIL]`
- Phones → `[PHONE]`
- Addresses → `[LOCATION]`
- Credit cards, SSNs, IPs, URLs → anonymized

## Reset

```bash
rm -rf ~/.cache/voice-synth
```
