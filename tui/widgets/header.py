"""Branded header widget with double border."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


VERSION = "0.3.0-alpha"


class BrandedHeader(Static):
    """Purple double-border header matching Gum aesthetic."""

    DEFAULT_CSS = """
    BrandedHeader {
        height: auto;
        width: 100%;
        content-align: center middle;
        border: double #9370DB;
        padding: 1 4;
        margin: 1 2;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #9370DB]Voice Synthesizer[/]\n"
            "[#8B8B8B]Email data preparation for GPT fine-tuning[/]\n"
            f"[#5C5C5C]v{VERSION}[/]",
            classes="header-content"
        )
