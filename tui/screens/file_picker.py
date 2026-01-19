"""File picker screen with drag-and-drop support."""

import os
import re
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from ..widgets.header import BrandedHeader


def clean_path(raw_path: str) -> str:
    """Clean up a path from drag-and-drop or copy-paste.

    Handles:
    - Surrounding quotes
    - Escaped spaces (\\ )
    - URL-encoded characters
    - Leading/trailing whitespace
    """
    path = raw_path.strip()

    # Remove surrounding quotes
    if (path.startswith("'") and path.endswith("'")) or \
       (path.startswith('"') and path.endswith('"')):
        path = path[1:-1]

    # Handle escaped spaces (common in macOS Finder drag-drop)
    path = path.replace("\\ ", " ")

    # Handle other common escapes
    path = re.sub(r"\\([^\\])", r"\1", path)

    # URL decode if needed (file:///...)
    if path.startswith("file://"):
        from urllib.parse import unquote
        path = unquote(path[7:])

    # Expand ~ to home directory
    path = os.path.expanduser(path)

    return path.strip()


class FilePickerScreen(Screen):
    """File picker with drag-and-drop instructions."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("enter", "submit", "Continue"),
    ]

    def compose(self) -> ComposeResult:
        yield BrandedHeader()

        with Center():
            with Vertical(id="picker-container", classes="centered-content"):
                yield Static(
                    "[bold #9370DB]Select Input File[/]",
                    classes="section-title"
                )
                yield Static(
                    "Drop your Google Takeout export below\n"
                    "(.mbox file, folder, or .zip)",
                    classes="section-subtitle"
                )
                yield Static(
                    "[italic #8B8B8B]Drag from Finder into this window, then press Enter[/]",
                    classes="file-hint"
                )
                yield Input(
                    placeholder="Drop file here or paste path...",
                    id="file-input",
                    classes="file-input"
                )
                yield Static(id="file-status")
                yield Button(
                    "Continue",
                    id="btn-continue",
                    classes="menu-button -primary",
                    disabled=True
                )
                yield Button(
                    "Back",
                    id="btn-back",
                    classes="menu-button"
                )

        yield Footer()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Validate file path as user types."""
        if event.input.id != "file-input":
            return

        raw_path = event.value
        if not raw_path.strip():
            self._update_status("", valid=None)
            return

        path = clean_path(raw_path)
        exists = os.path.exists(path)

        if exists:
            if os.path.isdir(path):
                self._update_status(f"[#00FF7F]Directory: {path}[/]", valid=True)
            elif path.lower().endswith(('.mbox', '.zip', '.json', '.jsonl')):
                size_mb = os.path.getsize(path) / (1024 * 1024)
                self._update_status(f"[#00FF7F]File: {os.path.basename(path)} ({size_mb:.1f} MB)[/]", valid=True)
            else:
                self._update_status(f"[#FFA500]Unsupported file type[/]", valid=False)
        else:
            self._update_status(f"[#FF6B6B]File not found[/]", valid=False)

    def _update_status(self, message: str, valid: bool | None) -> None:
        """Update status message and button state."""
        status = self.query_one("#file-status", Static)
        status.update(message)

        btn = self.query_one("#btn-continue", Button)
        btn.disabled = valid is not True

        # Update input style
        input_widget = self.query_one("#file-input", Input)
        input_widget.remove_class("-valid", "-invalid")
        if valid is True:
            input_widget.add_class("-valid")
        elif valid is False:
            input_widget.add_class("-invalid")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-continue":
            self._continue()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        if event.input.id == "file-input":
            btn = self.query_one("#btn-continue", Button)
            if not btn.disabled:
                self._continue()

    def _continue(self) -> None:
        """Continue to next screen with selected file."""
        raw_path = self.query_one("#file-input", Input).value
        path = clean_path(raw_path)

        if not os.path.exists(path):
            return

        # Store in app state
        self.app.input_file = os.path.abspath(path)
        self.app.work_dir = os.getcwd()

        # Go to sender filter screen
        from .sender_filter import SenderFilterScreen
        self.app.push_screen(SenderFilterScreen())

    def action_back(self) -> None:
        """Go back."""
        self.app.pop_screen()

    def action_submit(self) -> None:
        """Submit the form."""
        btn = self.query_one("#btn-continue", Button)
        if not btn.disabled:
            self._continue()
