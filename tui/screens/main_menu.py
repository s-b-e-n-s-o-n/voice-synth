"""Main menu screen with resume detection."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from ..jobs import JobTracker
from ..widgets.header import BrandedHeader


class MainMenuScreen(Screen):
    """Main menu with options and resume detection."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.job_tracker = JobTracker()
        self.incomplete_job = None

    def compose(self) -> ComposeResult:
        yield BrandedHeader()

        with Vertical(id="menu-container"):
            # Check for incomplete jobs
            self.incomplete_job = self.job_tracker.get_most_recent_incomplete()

            if self.incomplete_job:
                yield Button(
                    f"Continue previous ({self.incomplete_job.mbox_name})",
                    id="btn-resume",
                    classes="menu-button -resume",
                )

            yield Button(
                "Get started",
                id="btn-start",
                classes="menu-button -primary",
            )
            yield Button(
                "Help",
                id="btn-help",
                classes="menu-button",
            )
            yield Button(
                "Uninstall",
                id="btn-uninstall",
                classes="menu-button",
            )
            yield Button(
                "Quit",
                id="btn-quit",
                classes="menu-button",
            )

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "btn-resume":
            self._resume_job()
        elif button_id == "btn-start":
            self._start_new()
        elif button_id == "btn-help":
            self.app.action_help()
        elif button_id == "btn-uninstall":
            self._show_uninstall()
        elif button_id == "btn-quit":
            self.app.exit()

    def _start_new(self) -> None:
        """Start a new pipeline run."""
        from .file_picker import FilePickerScreen
        self.app.push_screen(FilePickerScreen())

    def _resume_job(self) -> None:
        """Resume an incomplete job."""
        if not self.incomplete_job:
            return

        # Set app state from job
        self.app.input_file = self.incomplete_job.mbox
        self.app.work_dir = self.incomplete_job.work_dir
        self.app.sender_email = self.incomplete_job.sender or ""

        # Go to progress screen to resume
        from .progress import ProgressScreen
        self.app.push_screen(ProgressScreen(resume=True))

    def _show_uninstall(self) -> None:
        """Show uninstall confirmation."""
        from .uninstall import UninstallScreen
        self.app.push_screen(UninstallScreen())

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()

    def action_help(self) -> None:
        """Show help."""
        self.app.action_help()
