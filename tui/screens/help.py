"""Help screen with markdown viewer."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Markdown

from ..widgets.header import BrandedHeader


HELP_CONTENT = """\
# Voice Synthesizer

Prepare email data for fine-tuning GPT models on your writing style.

## Pipeline Stages

| Stage | Name | Description |
|-------|------|-------------|
| 0 | **Import** | Import MBOX from Google Takeout, strip attachments |
| 1 | **Convert** | Convert JSON to JSONL, filter unsafe fields |
| 2 | **Clean** | Anonymize PII with Presidio, remove signatures |
| 3 | **Curate** | Score by richness, group by topic, output CSV |

## Quick Start

1. Go to [takeout.google.com](https://takeout.google.com)
2. Select **only Mail** → Export as **MBOX**
3. Run this tool and select your `.mbox` file
4. Enter your email to filter to emails **you wrote**
5. Review `style_shortlist.csv` in a spreadsheet

## CLI Usage

You can also run the pipeline directly from the command line:

```
./voice-synth run <file> --sender <email>
```

### Examples

```bash
# Full pipeline from Google Takeout zip
./voice-synth run takeout.zip --sender you@gmail.com

# From extracted folder
./voice-synth run ./Takeout/ --sender you@gmail.com

# Individual stages
./voice-synth import ./file.mbox --out emails.json
./voice-synth clean emails.jsonl --sender you@gmail.com
./voice-synth curate cleaned_emails.json --per-topic 100
```

## Files & Storage

Dependencies are installed to:
```
~/.cache/voice-synth/venv/
```

To reset, select "Uninstall" from the main menu or delete that directory.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `Escape` | Go back |
| `?` | Show this help |
| `Enter` | Confirm/Continue |

---

*Press `Escape` or `q` to close this help*
"""


class HelpScreen(Screen):
    """Markdown help viewer."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("q", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield BrandedHeader()
        yield Vertical(
            Markdown(HELP_CONTENT, id="help-content"),
            id="help-container"
        )
        yield Footer()

    def action_back(self) -> None:
        """Go back."""
        self.app.pop_screen()
