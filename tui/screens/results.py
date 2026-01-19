"""Results screen with summary table."""

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static

from ..widgets.header import BrandedHeader


class ResultsScreen(Screen):
    """Pipeline results summary."""

    BINDINGS = [
        ("enter", "done", "Done"),
        ("q", "done", "Done"),
    ]

    def compose(self) -> ComposeResult:
        yield BrandedHeader()

        with Center():
            with Vertical(id="results-container", classes="centered-content"):
                yield Static(
                    "[bold $success]Processing Complete![/]",
                    classes="results-header"
                )
                yield Static(
                    "",
                    id="output-path",
                    classes="results-path"
                )
                yield DataTable(id="results-table")
                yield Static(
                    "[italic dim]Open the CSV in a spreadsheet to review your emails[/]",
                    classes="section-subtitle"
                )
                yield Button(
                    "Done",
                    id="btn-done",
                    classes="menu-button -primary"
                )
                yield Button(
                    "Start Another",
                    id="btn-another",
                    classes="menu-button"
                )

        yield Footer()

    def on_mount(self) -> None:
        """Populate results when screen mounts."""
        results = self.app.pipeline_results

        # Show output path
        desktop_path = results.get("desktop_path", "style_shortlist.csv")
        if "Desktop" in str(desktop_path):
            display_path = "~/Desktop/style_shortlist.csv"
        else:
            display_path = os.path.basename(desktop_path)

        path_widget = self.query_one("#output-path", Static)
        path_widget.update(f"[$success]Output: {display_path}[/]")

        # Build results table
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Stage", "Input", "Output", "Filtered")

        # Import stage
        if "import" in results:
            imp = results["import"]
            table.add_row(
                "Import",
                f"{imp.get('total', 0):,}",
                f"{imp.get('imported', 0):,}",
                f"{imp.get('skipped', 0):,}"
            )

        # Convert stage
        if "convert" in results:
            conv = results["convert"]
            filtered = conv.get("total", 0) - conv.get("kept", 0)
            table.add_row(
                "Convert",
                f"{conv.get('total', 0):,}",
                f"{conv.get('kept', 0):,}",
                f"{filtered:,}"
            )

        # Clean stage
        if "clean" in results:
            clean = results["clean"]
            filtered = clean.get("total", 0) - clean.get("kept", 0)
            table.add_row(
                "Clean",
                f"{clean.get('total', 0):,}",
                f"{clean.get('kept', 0):,}",
                f"{filtered:,}"
            )

        # Curate stage
        if "curate" in results:
            curate = results["curate"]
            filtered = curate.get("total_input", 0) - curate.get("shortlisted", 0)
            table.add_row(
                "[bold]Curate[/]",
                f"{curate.get('total_input', 0):,}",
                f"[bold $success]{curate.get('shortlisted', 0):,}[/]",
                f"{filtered:,}"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-done":
            self._done()
        elif event.button.id == "btn-another":
            self._start_another()

    def _done(self) -> None:
        """Exit the application."""
        self.app.exit()

    def _start_another(self) -> None:
        """Start another pipeline run."""
        # Clear state
        self.app.input_file = ""
        self.app.sender_email = ""
        self.app.pipeline_results = {}

        # Pop all screens and go back to main menu
        while len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_done(self) -> None:
        """Done action."""
        self._done()
