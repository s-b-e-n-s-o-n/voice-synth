"""Main Textual App for Voice Synthesizer."""

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from .screens.main_menu import MainMenuScreen


class VoiceSynthApp(App):
    """Voice Synthesizer - Email data preparation TUI."""

    TITLE = "Voice Synthesizer"
    SUB_TITLE = "Email data preparation for GPT fine-tuning"

    CSS_PATH = Path(__file__).parent / "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "back", "Back", show=True),
        Binding("?", "help", "Help", show=True),
    ]

    # Pipeline state - shared across screens
    input_file: str = ""
    sender_email: str = ""
    work_dir: str = ""
    pipeline_results: dict = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.theme = "textual-dark"

    def on_mount(self) -> None:
        """Start with main menu screen."""
        self.push_screen(MainMenuScreen())

    def action_back(self) -> None:
        """Go back to previous screen."""
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def action_help(self) -> None:
        """Show help screen."""
        from .screens.help import HelpScreen
        self.push_screen(HelpScreen())

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()
