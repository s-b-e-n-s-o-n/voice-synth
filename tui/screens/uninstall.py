"""Uninstall confirmation screen."""

import os
import shutil
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from ..widgets.header import BrandedHeader


class UninstallScreen(Screen):
    """Uninstall confirmation dialog."""

    BINDINGS = [
        ("escape", "back", "Cancel"),
        ("n", "back", "No"),
    ]

    def compose(self) -> ComposeResult:
        yield BrandedHeader()

        cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "voice-synth"

        with Center():
            with Vertical(id="uninstall-container", classes="modal-dialog"):
                yield Static(
                    "[bold $primary]Uninstall[/]",
                    classes="modal-title"
                )
                yield Static(
                    "This will delete all downloaded tools and dependencies.",
                    classes="modal-body"
                )
                yield Static(
                    f"[dim italic]{cache_dir}[/]",
                    classes="modal-body"
                )
                with Horizontal(classes="modal-buttons"):
                    yield Button(
                        "Cancel",
                        id="btn-cancel",
                        classes="modal-button"
                    )
                    yield Button(
                        "Uninstall",
                        id="btn-confirm",
                        variant="error",
                        classes="modal-button"
                    )

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-cancel":
            self.app.pop_screen()
        elif event.button.id == "btn-confirm":
            self._do_uninstall()

    def _do_uninstall(self) -> None:
        """Perform the uninstall."""
        cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "voice-synth"

        try:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)

            # Show success and exit
            self.notify("Uninstalled successfully. Run ./voice-synth to reinstall.", severity="information")
            self.app.exit()

        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            self.app.pop_screen()

    def action_back(self) -> None:
        """Cancel."""
        self.app.pop_screen()
