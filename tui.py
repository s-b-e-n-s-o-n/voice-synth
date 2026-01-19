#!/usr/bin/env python3
"""
Textual TUI for Voice Synthesizer.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Header, Footer, Button, Static, Input, Label, DataTable, ProgressBar
from textual.binding import Binding

# Add script dir to path for pipeline import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Paths
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "voice-synth"
JOBS_FILE = CACHE_DIR / "jobs.json"
VERSION = "0.4.0-alpha"


# =============================================================================
# Job Tracking
# =============================================================================

def load_jobs():
    """Load jobs from file."""
    if not JOBS_FILE.exists():
        return []
    try:
        return json.loads(JOBS_FILE.read_text())
    except Exception:
        return []


def save_job(mbox_path: str, work_dir: str, status: str, sender: Optional[str] = None):
    """Save a job."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = load_jobs()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update existing or add new
    found = False
    for job in jobs:
        if job.get('mbox') == mbox_path and job.get('work_dir') == work_dir:
            job['status'] = status
            job['updated'] = timestamp
            if sender:
                job['sender'] = sender
            found = True
            break

    if not found:
        jobs.append({
            'mbox': mbox_path,
            'work_dir': work_dir,
            'status': status,
            'started': timestamp,
            'updated': timestamp,
            'sender': sender,
        })

    # Keep last 10
    jobs.sort(key=lambda x: x.get('updated', ''), reverse=True)
    jobs = jobs[:10]

    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


def get_incomplete_job():
    """Get most recent incomplete job."""
    for job in load_jobs():
        if job.get('status') != 'in_progress':
            continue
        work_dir = job.get('work_dir', '')
        if not os.path.isdir(work_dir):
            continue
        # Check for intermediate files
        if os.path.exists(os.path.join(work_dir, 'style_shortlist.csv')):
            continue
        if any(os.path.exists(os.path.join(work_dir, f))
               for f in ['emails_raw.json', 'emails.jsonl', 'cleaned_emails.json']):
            return job
    return None


def mark_job_complete(work_dir: str):
    """Mark jobs in work_dir as complete."""
    jobs = load_jobs()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for job in jobs:
        if job.get('work_dir') == work_dir:
            job['status'] = 'completed'
            job['updated'] = timestamp
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


def clean_path(raw_path: str) -> str:
    """Clean drag-and-drop path."""
    path = raw_path.strip()
    if (path.startswith("'") and path.endswith("'")) or \
       (path.startswith('"') and path.endswith('"')):
        path = path[1:-1]
    path = path.replace("\\ ", " ")
    if path.startswith("file://"):
        from urllib.parse import unquote
        path = unquote(path[7:])
    return os.path.expanduser(path).strip()


# =============================================================================
# CSS Styles
# =============================================================================

CSS = """
Screen {
    background: $surface;
}

#main-container {
    width: 100%;
    height: 100%;
    align: center middle;
}

.menu-container {
    width: 60;
    height: auto;
    padding: 1 2;
    border: double $primary;
    background: $surface;
}

.title {
    text-align: center;
    text-style: bold;
    color: $primary;
    padding: 1 0;
}

.subtitle {
    text-align: center;
    color: $text-muted;
    padding: 0 0 1 0;
}

.menu-button {
    width: 100%;
    margin: 1 0 0 0;
}

.menu-button:focus {
    background: $primary;
}

#file-input {
    width: 100%;
    margin: 1 0;
}

.help-text {
    color: $text-muted;
    text-align: center;
    padding: 1 0;
}

.error-text {
    color: $error;
    text-align: center;
    padding: 1 0;
}

.success-text {
    color: $success;
    text-align: center;
    padding: 1 0;
}

#progress-container {
    width: 80;
    height: auto;
    padding: 2;
    border: double $primary;
    background: $surface;
}

.stage-item {
    padding: 0 1;
}

.stage-pending {
    color: $text-muted;
}

.stage-running {
    color: $warning;
}

.stage-complete {
    color: $success;
}

.stage-error {
    color: $error;
}

#results-container {
    width: 80;
    height: auto;
    padding: 2;
    border: double $success;
    background: $surface;
}
"""


# =============================================================================
# Screens
# =============================================================================

class MainMenuScreen(Screen):
    """Main menu screen."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Voice Synthesizer", classes="title"),
                Static(f"Email data preparation for GPT fine-tuning\nv{VERSION}", classes="subtitle"),
                Button("Get Started", id="btn-start", classes="menu-button", variant="primary"),
                Button("Help", id="btn-help", classes="menu-button"),
                Button("Uninstall", id="btn-uninstall", classes="menu-button"),
                Button("Quit", id="btn-quit", classes="menu-button"),
                classes="menu-container",
            ),
            id="main-container",
        )

    def on_mount(self) -> None:
        # Check for incomplete jobs
        incomplete = get_incomplete_job()
        if incomplete:
            mbox_name = os.path.basename(incomplete.get('mbox', 'unknown'))
            # Insert resume button at the top
            container = self.query_one(".menu-container")
            resume_btn = Button(f"Resume ({mbox_name})", id="btn-resume", classes="menu-button", variant="success")
            container.mount(resume_btn, after=self.query_one(".subtitle"))
            self.app.incomplete_job = incomplete

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start":
            self.app.push_screen(FilePickerScreen())
        elif event.button.id == "btn-resume":
            job = getattr(self.app, 'incomplete_job', None)
            if job:
                self.app.input_file = job.get('mbox', '')
                self.app.sender = job.get('sender', '')
                self.app.work_dir = job.get('work_dir', os.getcwd())
                self.app.push_screen(ProgressScreen())
        elif event.button.id == "btn-help":
            self.app.push_screen(HelpScreen())
        elif event.button.id == "btn-uninstall":
            self.app.push_screen(UninstallScreen())
        elif event.button.id == "btn-quit":
            self.app.exit()

    def action_quit(self) -> None:
        self.app.exit()


class FilePickerScreen(Screen):
    """File picker screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Select Input File", classes="title"),
                Static("Drop your Google Takeout export (.mbox, folder, or .zip)", classes="subtitle"),
                Input(placeholder="Drag file here or type path...", id="file-input"),
                Static("Drag from Finder into this window, then press Enter", classes="help-text"),
                Static("", id="error-msg", classes="error-text"),
                Horizontal(
                    Button("Back", id="btn-back"),
                    Button("Continue", id="btn-continue", variant="primary"),
                ),
                classes="menu-container",
            ),
            id="main-container",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._validate_and_continue()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-continue":
            self._validate_and_continue()

    def _validate_and_continue(self) -> None:
        raw_path = self.query_one("#file-input", Input).value
        if not raw_path:
            self.query_one("#error-msg", Static).update("Please enter a file path")
            return

        path = clean_path(raw_path)

        if not os.path.exists(path):
            self.query_one("#error-msg", Static).update(f"File not found: {path}")
            return

        self.app.input_file = os.path.abspath(path)
        self.app.push_screen(SenderFilterScreen())

    def action_back(self) -> None:
        self.app.pop_screen()


class SenderFilterScreen(Screen):
    """Sender filter screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Sender Filter", classes="title"),
                Static("Filter to emails you wrote (not received)", classes="subtitle"),
                Static("Detecting your email address...", id="detect-status", classes="help-text"),
                Input(placeholder="Enter email address...", id="sender-input"),
                Horizontal(
                    Button("Skip (no filter)", id="btn-skip"),
                    Button("Continue", id="btn-continue", variant="primary"),
                ),
                classes="menu-container",
            ),
            id="main-container",
        )

    def on_mount(self) -> None:
        self._detect_owner()

    @work(thread=True)
    def _detect_owner(self) -> None:
        """Try to detect owner email."""
        try:
            from pipeline import detect_owner_email
            detected = detect_owner_email(self.app.input_file)
            if detected:
                self.call_from_thread(self._set_detected, detected)
            else:
                self.call_from_thread(self._set_not_detected)
        except Exception:
            self.call_from_thread(self._set_not_detected)

    def _set_detected(self, email: str) -> None:
        self.query_one("#detect-status", Static).update(f"Detected: {email}")
        self.query_one("#sender-input", Input).value = email

    def _set_not_detected(self) -> None:
        self.query_one("#detect-status", Static).update("Could not auto-detect email")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-skip":
            self.app.sender = ""
            self.app.work_dir = os.getcwd()
            self.app.push_screen(ProgressScreen())
        elif event.button.id == "btn-continue":
            self.app.sender = self.query_one("#sender-input", Input).value
            self.app.work_dir = os.getcwd()
            self.app.push_screen(ProgressScreen())

    def action_back(self) -> None:
        self.app.pop_screen()


class ProgressScreen(Screen):
    """Pipeline progress screen."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Processing Emails", classes="title"),
                Static("This may take a few minutes for large mailboxes", classes="subtitle"),
                Static("○ Import MBOX", id="stage-import", classes="stage-item stage-pending"),
                Static("○ Convert to JSONL", id="stage-convert", classes="stage-item stage-pending"),
                Static("○ Clean & anonymize", id="stage-clean", classes="stage-item stage-pending"),
                Static("○ Curate shortlist", id="stage-curate", classes="stage-item stage-pending"),
                Static("", id="status-msg", classes="help-text"),
                id="progress-container",
            ),
            id="main-container",
        )

    def on_mount(self) -> None:
        self._run_pipeline()

    @work(thread=True)
    def _run_pipeline(self) -> None:
        """Run the pipeline stages."""
        input_file = self.app.input_file
        sender = self.app.sender
        work_dir = self.app.work_dir

        # Save job
        save_job(input_file, work_dir, "in_progress", sender)

        original_dir = os.getcwd()
        os.chdir(work_dir)

        try:
            from pipeline import (
                import_mbox, convert_to_jsonl, clean_emails, build_shortlist,
                needs_mbox_import
            )

            results = {}

            # Stage 0: Import
            if needs_mbox_import(input_file):
                self.call_from_thread(self._update_stage, "import", "running")
                results["import"] = import_mbox(input_file, "emails_raw.json", quiet=True)
                self.call_from_thread(self._update_stage, "import", "complete",
                                      f"Imported {results['import'].get('imported', 0):,} emails")
                input_file = "emails_raw.json"
            else:
                self.call_from_thread(self._update_stage, "import", "complete", "Skipped (not MBOX)")

            # Stage 1: Convert
            self.call_from_thread(self._update_stage, "convert", "running")
            results["convert"] = convert_to_jsonl(input_file, "emails.jsonl", quiet=True)
            self.call_from_thread(self._update_stage, "convert", "complete",
                                  f"Converted {results['convert'].get('kept', 0):,} records")

            # Stage 2: Clean
            self.call_from_thread(self._update_stage, "clean", "running")
            results["clean"] = clean_emails("emails.jsonl", "cleaned_emails.json", sender or None, quiet=True)
            self.call_from_thread(self._update_stage, "clean", "complete",
                                  f"Cleaned {results['clean'].get('kept', 0):,} emails")

            # Stage 3: Curate
            self.call_from_thread(self._update_stage, "curate", "running")
            results["curate"] = build_shortlist("cleaned_emails.json", "style_shortlist.csv", quiet=True)
            self.call_from_thread(self._update_stage, "curate", "complete",
                                  f"Selected {results['curate'].get('shortlisted', 0):,} emails")

            # Copy to Desktop
            desktop = Path.home() / "Desktop" / "style_shortlist.csv"
            try:
                shutil.copy("style_shortlist.csv", desktop)
                results["desktop_path"] = str(desktop)
            except Exception:
                results["desktop_path"] = os.path.abspath("style_shortlist.csv")

            mark_job_complete(work_dir)
            self.app.results = results
            self.call_from_thread(self._show_results)

        except Exception as e:
            self.call_from_thread(self._show_error, str(e))

        finally:
            os.chdir(original_dir)

    def _update_stage(self, stage: str, status: str, msg: str = "") -> None:
        widget = self.query_one(f"#stage-{stage}", Static)
        if status == "running":
            widget.update(f"◐ {widget.renderable.plain[2:]}")
            widget.set_classes("stage-item stage-running")
        elif status == "complete":
            label = msg or widget.renderable.plain[2:]
            widget.update(f"✓ {label}")
            widget.set_classes("stage-item stage-complete")
        elif status == "error":
            widget.update(f"✗ {msg or 'Error'}")
            widget.set_classes("stage-item stage-error")

    def _show_results(self) -> None:
        self.app.push_screen(ResultsScreen())

    def _show_error(self, error: str) -> None:
        self.query_one("#status-msg", Static).update(f"Error: {error}")

    def action_cancel(self) -> None:
        # TODO: Actually cancel the worker
        self.app.pop_screen()


class ResultsScreen(Screen):
    """Results display screen."""

    BINDINGS = [
        Binding("enter", "done", "Done"),
        Binding("escape", "done", "Done"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Processing Complete!", classes="title success-text"),
                Static("", id="output-path", classes="help-text"),
                DataTable(id="results-table"),
                Static("Open the CSV in a spreadsheet to review your emails", classes="help-text"),
                Button("Done", id="btn-done", variant="success"),
                id="results-container",
            ),
            id="main-container",
        )

    def on_mount(self) -> None:
        results = getattr(self.app, 'results', {})

        # Show output path
        desktop_path = results.get("desktop_path", "style_shortlist.csv")
        if "Desktop" in str(desktop_path):
            self.query_one("#output-path", Static).update("Output: ~/Desktop/style_shortlist.csv")
        else:
            self.query_one("#output-path", Static).update(f"Output: {desktop_path}")

        # Build results table
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Stage", "Input", "Output", "Filtered")

        if "import" in results:
            imp = results["import"]
            table.add_row("Import", f"{imp.get('total', 0):,}", f"{imp.get('imported', 0):,}", f"{imp.get('skipped', 0):,}")

        if "convert" in results:
            conv = results["convert"]
            table.add_row("Convert", f"{conv.get('total', 0):,}", f"{conv.get('kept', 0):,}",
                         f"{conv.get('total', 0) - conv.get('kept', 0):,}")

        if "clean" in results:
            clean = results["clean"]
            table.add_row("Clean", f"{clean.get('total', 0):,}", f"{clean.get('kept', 0):,}",
                         f"{clean.get('total', 0) - clean.get('kept', 0):,}")

        if "curate" in results:
            curate = results["curate"]
            table.add_row("Curate", f"{curate.get('total_input', 0):,}", f"{curate.get('shortlisted', 0):,}",
                         f"{curate.get('total_input', 0) - curate.get('shortlisted', 0):,}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-done":
            self.app.exit()

    def action_done(self) -> None:
        self.app.exit()


class HelpScreen(Screen):
    """Help screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        help_text = """[bold]Pipeline Stages[/]

[bold]0. Import[/]   - Import MBOX from Google Takeout, strip attachments
[bold]1. Convert[/]  - Convert JSON to JSONL, filter unsafe fields
[bold]2. Clean[/]    - Anonymize PII with Presidio, remove signatures
[bold]3. Curate[/]   - Score by richness, group by topic, output CSV

[bold]Quick Start[/]

1. Go to https://takeout.google.com
2. Select only Mail → Export as MBOX
3. Run this tool and select your .mbox file
4. Enter your email to filter to emails you wrote
5. Review style_shortlist.csv in a spreadsheet

[bold]CLI Usage[/]

./voice-synth run <file> --sender <email>

[bold]Files[/]

Dependencies: ~/.cache/voice-synth/venv/"""

        yield Container(
            Vertical(
                Static("Help", classes="title"),
                Static(help_text, classes="help-text"),
                Button("Back", id="btn-back"),
                classes="menu-container",
            ),
            id="main-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


class UninstallScreen(Screen):
    """Uninstall confirmation screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Uninstall", classes="title"),
                Static(f"This will delete: {CACHE_DIR}", classes="help-text"),
                Horizontal(
                    Button("Cancel", id="btn-cancel"),
                    Button("Delete Everything", id="btn-confirm", variant="error"),
                ),
                classes="menu-container",
            ),
            id="main-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.app.pop_screen()
        elif event.button.id == "btn-confirm":
            try:
                if CACHE_DIR.exists():
                    shutil.rmtree(CACHE_DIR)
                self.app.exit(message="Uninstalled successfully. Run ./voice-synth to reinstall.")
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

    def action_back(self) -> None:
        self.app.pop_screen()


# =============================================================================
# Main App
# =============================================================================

class VoiceSynthApp(App):
    """Voice Synthesizer TUI Application."""

    CSS = CSS
    TITLE = "Voice Synthesizer"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    # State
    input_file: str = ""
    sender: str = ""
    work_dir: str = ""
    results: dict = {}
    incomplete_job: Optional[dict] = None

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen())

    def action_quit(self) -> None:
        self.exit()


def main():
    """Entry point."""
    app = VoiceSynthApp()
    app.run()


if __name__ == "__main__":
    main()
