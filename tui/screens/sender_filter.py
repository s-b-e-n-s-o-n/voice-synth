"""Sender filter screen with auto-detection."""

import os
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from ..widgets.header import BrandedHeader


class SenderFilterScreen(Screen):
    """Sender email selection with auto-detection."""

    BINDINGS = [
        ("escape", "back", "Back"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.detected_email = None

    def compose(self) -> ComposeResult:
        yield BrandedHeader()

        with Center():
            with Vertical(id="sender-container", classes="centered-content"):
                yield Static(
                    "[bold $primary]Sender Filter[/]",
                    classes="section-title"
                )
                yield Static(
                    "Filter to emails you wrote (not received)",
                    classes="section-subtitle"
                )
                yield Static(
                    "[$primary]Detecting your email address...[/]",
                    id="detection-status"
                )
                yield OptionList(id="sender-options")
                yield Input(
                    placeholder="Enter email address...",
                    id="sender-input",
                    classes="file-input"
                )
                yield Button(
                    "Continue",
                    id="btn-continue",
                    classes="menu-button -primary"
                )
                yield Button(
                    "Back",
                    id="btn-back",
                    classes="menu-button"
                )

        yield Footer()

    def on_mount(self) -> None:
        """Detect owner email when screen mounts."""
        self._detect_owner()

    def _detect_owner(self) -> None:
        """Try to detect the mailbox owner's email."""
        input_file = self.app.input_file
        if not input_file:
            self._show_manual_entry()
            return

        # Add the script directory to path so we can import pipeline
        script_dir = Path(__file__).resolve().parent.parent.parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))

        try:
            from pipeline import detect_owner_email
            self.detected_email = detect_owner_email(input_file)
        except Exception:
            self.detected_email = None

        if self.detected_email:
            self._show_detected(self.detected_email)
        else:
            self._show_manual_entry()

    def _show_detected(self, email: str) -> None:
        """Show detected email with options."""
        status = self.query_one("#detection-status", Static)
        status.update(f"[$success]Detected: {email}[/]")

        options = self.query_one("#sender-options", OptionList)
        options.clear_options()
        options.add_option(Option(f"Yes, use {email}", id="use-detected"))
        options.add_option(Option("Enter a different email", id="enter-manual"))
        options.add_option(Option("Keep all senders (no filter)", id="no-filter"))
        options.display = True

        # Hide input initially
        input_widget = self.query_one("#sender-input", Input)
        input_widget.display = False

    def _show_manual_entry(self) -> None:
        """Show manual email entry."""
        status = self.query_one("#detection-status", Static)
        status.update("[dim]Could not detect email. Enter manually or skip filter.[/]")

        options = self.query_one("#sender-options", OptionList)
        options.clear_options()
        options.add_option(Option("Enter email address", id="enter-manual"))
        options.add_option(Option("Keep all senders (no filter)", id="no-filter"))
        options.display = True

        input_widget = self.query_one("#sender-input", Input)
        input_widget.display = False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        option_id = event.option.id

        if option_id == "use-detected":
            self.app.sender_email = self.detected_email
            self._continue()
        elif option_id == "enter-manual":
            # Show input field
            input_widget = self.query_one("#sender-input", Input)
            input_widget.display = True
            input_widget.value = self.detected_email or ""
            input_widget.focus()
        elif option_id == "no-filter":
            self.app.sender_email = ""
            self._continue()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in email input."""
        if event.input.id == "sender-input":
            email = event.value.strip()
            if email:
                self.app.sender_email = email
                self._continue()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-continue":
            self._submit()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    def _submit(self) -> None:
        """Submit the current selection."""
        # Check if input is visible and has value
        input_widget = self.query_one("#sender-input", Input)
        if input_widget.display and input_widget.value.strip():
            self.app.sender_email = input_widget.value.strip()
            self._continue()
        elif self.detected_email:
            # Default to detected email if available
            self.app.sender_email = self.detected_email
            self._continue()
        else:
            # No filter
            self.app.sender_email = ""
            self._continue()

    def _continue(self) -> None:
        """Continue to progress screen."""
        from .progress import ProgressScreen
        self.app.push_screen(ProgressScreen())

    def action_back(self) -> None:
        """Go back."""
        self.app.pop_screen()
