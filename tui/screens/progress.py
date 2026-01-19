"""Progress screen with pipeline workers."""

import os
import sys
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Footer, ProgressBar, Static
from textual.worker import Worker, get_current_worker

from ..jobs import JobTracker
from ..widgets.header import BrandedHeader
from ..widgets.stage_tracker import StageTracker, StageStatus


class PipelineComplete(Message):
    """Sent when pipeline completes."""

    def __init__(self, results: dict):
        super().__init__()
        self.results = results


class PipelineError(Message):
    """Sent when pipeline errors."""

    def __init__(self, error: str, stage: int):
        super().__init__()
        self.error = error
        self.stage = stage


class ProgressScreen(Screen):
    """Pipeline progress with threaded workers."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, resume: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.resume = resume
        self.job_tracker = JobTracker()
        self.worker: Optional[Worker] = None
        self.cancelled = False

    def compose(self) -> ComposeResult:
        yield BrandedHeader()

        with Center():
            with Vertical(id="progress-container", classes="centered-content"):
                yield Static(
                    "[bold $primary]Processing Emails[/]",
                    classes="section-title"
                )
                yield Static(
                    "[italic dim]This may take a few minutes for large mailboxes[/]",
                    classes="section-subtitle"
                )
                yield StageTracker(id="stage-tracker")
                yield ProgressBar(id="progress-bar", show_eta=True)
                yield Static("", id="progress-detail")
                yield Button(
                    "Cancel",
                    id="btn-cancel",
                    classes="menu-button"
                )

        yield Footer()

    def on_mount(self) -> None:
        """Start the pipeline when screen mounts."""
        self._start_pipeline()

    def _start_pipeline(self) -> None:
        """Start the pipeline worker."""
        # Save job as in_progress
        self.job_tracker.save_job(
            mbox_path=self.app.input_file,
            work_dir=self.app.work_dir,
            status="in_progress",
            sender=self.app.sender_email or None
        )

        # Start worker
        self.worker = self.run_worker(self._run_pipeline, thread=True)

    def _run_pipeline(self) -> dict:
        """Run the pipeline in a worker thread."""
        worker = get_current_worker()

        # Add script dir to path
        script_dir = Path(__file__).resolve().parent.parent.parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))

        # Change to work directory
        original_dir = os.getcwd()
        os.chdir(self.app.work_dir)

        try:
            from pipeline import (
                import_mbox, convert_to_jsonl, clean_emails, build_shortlist,
                needs_mbox_import
            )

            results = {}
            input_path = self.app.input_file
            sender = self.app.sender_email or None

            # Determine starting point if resuming
            start_stage = 0
            if self.resume:
                if os.path.exists("cleaned_emails.json"):
                    start_stage = 3
                elif os.path.exists("emails.jsonl"):
                    start_stage = 2
                elif os.path.exists("emails_raw.json"):
                    start_stage = 1

            tracker = self.query_one("#stage-tracker", StageTracker)

            # Mark skipped stages as complete
            for i in range(start_stage):
                self.call_from_thread(tracker.set_stage_complete, i, "skipped")

            # Stage 0: Import MBOX
            if start_stage <= 0 and needs_mbox_import(input_path):
                if worker.is_cancelled:
                    return {"cancelled": True}
                self.call_from_thread(tracker.set_stage_running, 0)

                # Check if already exists
                if os.path.exists("emails_raw.json") and not self.resume:
                    self.call_from_thread(tracker.set_stage_complete, 0, "cached")
                else:
                    results["import"] = import_mbox(input_path, "emails_raw.json", quiet=True)
                    count = results["import"].get("imported", 0)
                    self.call_from_thread(tracker.set_stage_complete, 0, f"{count:,} emails")

                input_path = "emails_raw.json"

            # Stage 1: Convert
            if start_stage <= 1:
                if worker.is_cancelled:
                    return {"cancelled": True}
                self.call_from_thread(tracker.set_stage_running, 1)

                if os.path.exists("emails.jsonl") and start_stage > 0:
                    self.call_from_thread(tracker.set_stage_complete, 1, "cached")
                else:
                    results["convert"] = convert_to_jsonl(input_path, "emails.jsonl", quiet=True)
                    count = results["convert"].get("kept", 0)
                    self.call_from_thread(tracker.set_stage_complete, 1, f"{count:,} records")

            # Stage 2: Clean
            if start_stage <= 2:
                if worker.is_cancelled:
                    return {"cancelled": True}
                self.call_from_thread(tracker.set_stage_running, 2)

                if os.path.exists("cleaned_emails.json") and start_stage > 1:
                    self.call_from_thread(tracker.set_stage_complete, 2, "cached")
                else:
                    results["clean"] = clean_emails(
                        "emails.jsonl",
                        "cleaned_emails.json",
                        sender_email=sender,
                        quiet=True
                    )
                    count = results["clean"].get("kept", 0)
                    self.call_from_thread(tracker.set_stage_complete, 2, f"{count:,} cleaned")

            # Stage 3: Curate
            if worker.is_cancelled:
                return {"cancelled": True}
            self.call_from_thread(tracker.set_stage_running, 3)

            results["curate"] = build_shortlist(
                "cleaned_emails.json",
                "style_shortlist.csv",
                quiet=True
            )
            count = results["curate"].get("shortlisted", 0)
            self.call_from_thread(tracker.set_stage_complete, 3, f"{count:,} selected")

            # Copy to Desktop
            desktop = Path.home() / "Desktop" / "style_shortlist.csv"
            try:
                import shutil
                shutil.copy("style_shortlist.csv", desktop)
                results["desktop_path"] = str(desktop)
            except Exception:
                results["desktop_path"] = os.path.abspath("style_shortlist.csv")

            return results

        except Exception as e:
            # Find which stage failed
            tracker = self.query_one("#stage-tracker", StageTracker)
            for i, stage in enumerate(tracker.stages):
                if stage.status == StageStatus.RUNNING:
                    self.call_from_thread(tracker.set_stage_error, i, str(e)[:30])
                    break
            raise

        finally:
            os.chdir(original_dir)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        if event.state.name == "SUCCESS":
            results = event.worker.result
            if results and not results.get("cancelled"):
                # Mark job complete
                self.job_tracker.mark_completed(self.app.work_dir)
                self.app.pipeline_results = results
                # Go to results screen
                from .results import ResultsScreen
                self.app.push_screen(ResultsScreen())

        elif event.state.name == "ERROR":
            # Show error
            error = str(event.worker.error) if event.worker.error else "Unknown error"
            self._show_error(error)

        elif event.state.name == "CANCELLED":
            self.app.pop_screen()

    def _show_error(self, error: str) -> None:
        """Display error message."""
        detail = self.query_one("#progress-detail", Static)
        detail.update(f"[$error]Error: {error}[/]")

        btn = self.query_one("#btn-cancel", Button)
        btn.label = "Back"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-cancel":
            self._cancel()

    def _cancel(self) -> None:
        """Cancel the pipeline."""
        if self.worker and self.worker.is_running:
            self.worker.cancel()
            self.cancelled = True
        else:
            self.app.pop_screen()

    def action_cancel(self) -> None:
        """Cancel action."""
        self._cancel()
