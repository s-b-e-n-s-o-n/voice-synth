# Potential Enhancements

The current pipeline stops at `style_shortlist.csv` for manual review. These enhancements would complete the journey from raw emails to fine-tuned model—and eliminate the CSV step entirely.

## Priority 1: Complete the Pipeline

### Stage 4: Review (replaces CSV export)

Interactive review directly in the TUI. No spreadsheet needed.

```bash
./voice-synth review cleaned_emails.json
```

**Features:**
- Page through candidates one at a time
- Keyboard shortcuts: `y` include, `n` skip, `s` star, `q` quit
- Show topic, length, richness score, token count
- Save progress (resume later)
- Outputs approved emails directly to JSON

**Output:** `reviewed_emails.json` (only approved emails)

### Stage 5: Format for Fine-Tuning

Convert reviewed JSON to OpenAI's JSONL format.

```bash
./voice-synth format reviewed_emails.json --out training_data.jsonl
```

**Output format:**
```jsonl
{"messages": [{"role": "system", "content": "Write emails in the user's personal style."}, {"role": "user", "content": "Write an email about: project status update"}, {"role": "assistant", "content": "Subject: Quick update\n\nHey team,..."}]}
```

**Features:**
- Generate user prompts from subject/topic
- Escape newlines properly in body content
- Validate against OpenAI's format requirements
- Train/validation split (80/20 default)
- Token counting and cost estimation

**Output:**
```
training_data_train.jsonl (80 examples, ~45K tokens, ~$0.14)
training_data_val.jsonl   (20 examples, ~11K tokens)
```

## Priority 2: Quality Insights

### Stats Dashboard

Stats before you commit to fine-tuning.

```bash
./voice-synth stats reviewed_emails.json
```

**Output:**
```
Total emails: 847
Token distribution: min=45, max=2,340, avg=312
Topic balance:
  client:   142 (17%)
  strategy: 98  (12%)
  update:   234 (28%)
  feedback: 156 (18%)
  workshop: 89  (11%)
  other:    128 (15%)
Potential duplicates: 12
Estimated fine-tuning cost: $0.89
```

## ~~Priority 2.5: Deduplication~~ IMPLEMENTED

Deduplication is now built into Stage 3 (Curate) and enabled by default.

```bash
# Dedup is on by default
./voice-synth curate cleaned_emails.json

# Disable if needed
./voice-synth curate cleaned_emails.json --no-dedupe

# Adjust similarity threshold (default 0.8)
./voice-synth curate cleaned_emails.json --dedupe-threshold 0.9
```

**What it does:**
- **Level 1:** Exact match via SHA-256 hash of normalized body
- **Level 2:** Near-duplicate detection via MinHash LSH (Jaccard similarity)
- Keeps the richest (longest + most paragraphs) version when duplicates found
- Reports stats: exact dupes removed, near-dupes removed

## Priority 3: Smarter Processing

### Conversation Pairing

Match email threads to create request/response training pairs.

```bash
./voice-synth pair cleaned_emails.json --out conversations.jsonl
```

**Features:**
- Thread detection via Message-ID/In-Reply-To headers
- Extract incoming email as "user" prompt
- Your reply as "assistant" response
- Filter to only complete pairs

### ML-Based Topic Classification

Replace keyword matching with embeddings.

**Current:** Keyword lists (`"proposal" → client`)
**Enhanced:** Sentence embeddings + clustering

Benefits:
- Catches emails that don't use expected keywords
- More accurate categorization
- Can discover new topic clusters

### Advanced Quality Scoring

Beyond length + paragraph count.

**Additional signals:**
- Vocabulary richness (unique words / total words)
- Sentence variety (length distribution)
- Readability score (Flesch-Kincaid)
- Tone detection (formal/casual)

## Implementation Notes

### Data Format at Each Stage

| Stage | Input | Output |
|-------|-------|--------|
| 0: Import | `.mbox` | `emails_raw.json` |
| 1: Convert | `.json` | `emails.jsonl` |
| 2: Clean | `.jsonl` | `cleaned_emails.json` |
| 3: Curate | `.json` | `candidates.json` |
| **4: Review** | `.json` | `reviewed_emails.json` |
| **5: Format** | `.json` | `*_train.jsonl`, `*_val.jsonl` |

### Token Limits

| Model | Max Tokens/Example |
|-------|-------------------|
| gpt-4o-mini | 16,385 |
| gpt-4o | 128,000 |
| gpt-3.5-turbo | 16,385 |

### Fine-Tuning Costs (as of Jan 2025)

| Model | Training | Inference (input) | Inference (output) |
|-------|----------|-------------------|-------------------|
| gpt-4o-mini | $3.00/1M tokens | $0.30/1M | $1.20/1M |
| gpt-4o | $25.00/1M tokens | $2.50/1M | $10.00/1M |

### Recommended Dataset Size

| Quality Level | Examples |
|---------------|----------|
| Minimum | 10 |
| Good starting point | 50 |
| Production quality | 100+ |

Research shows quality matters more than quantity for style transfer.

## References

- [OpenAI Fine-Tuning Guide](https://platform.openai.com/docs/guides/supervised-fine-tuning)
- [Fine-Tuning Best Practices](https://platform.openai.com/docs/guides/fine-tuning-best-practices)
- [OpenAI Cookbook: Chat Fine-tuning](https://cookbook.openai.com/examples/how_to_finetune_chat_models)
- [FinetuneDB: Email Writing Style](https://finetunedb.com/blog/how-to-fine-tune-gpt-3-5-for-email-writing-style/)
- [data-preparation-for-fine-tuning](https://github.com/yigitkonur/data-preparation-for-fine-tuning)
