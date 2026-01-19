"""Multi-stage progress indicator widget."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class StageStatus(Enum):
    """Status of a pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class Stage:
    """A pipeline stage."""
    name: str
    description: str
    status: StageStatus = StageStatus.PENDING
    progress: Optional[int] = None  # 0-100 for running stages
    detail: str = ""  # e.g., "1,234 / 5,000 emails"


class StageUpdate(Message):
    """Message sent when a stage status changes."""

    def __init__(self, stage_index: int, status: StageStatus, progress: Optional[int] = None, detail: str = ""):
        super().__init__()
        self.stage_index = stage_index
        self.status = status
        self.progress = progress
        self.detail = detail


class StageTracker(Static):
    """Widget showing pipeline stages with status indicators.

    Status indicators:
    - ○ pending (dim)
    - ◐ running (purple, animated)
    - ✓ complete (green)
    - ✗ error (red)
    """

    DEFAULT_CSS = """
    StageTracker {
        height: auto;
        width: 100%;
        padding: 0 2;
        margin: 1 0;
    }
    """

    # Default pipeline stages
    DEFAULT_STAGES = [
        Stage("Import", "Converting MBOX to JSON"),
        Stage("Convert", "Normalizing to JSONL format"),
        Stage("Clean", "Anonymizing PII with Presidio"),
        Stage("Curate", "Building quality shortlist"),
    ]

    stages: reactive[List[Stage]] = reactive(list)

    def __init__(self, stages: Optional[List[Stage]] = None, **kwargs):
        super().__init__(**kwargs)
        self.stages = stages or [Stage(s.name, s.description) for s in self.DEFAULT_STAGES]
        self._spinner_frame = 0

    def compose(self) -> ComposeResult:
        yield Static(id="stages-display")

    def on_mount(self) -> None:
        """Update display when mounted."""
        self._update_display()
        # Start spinner animation for running stages
        self.set_interval(0.1, self._animate_spinner)

    def _animate_spinner(self) -> None:
        """Animate spinner for running stages."""
        has_running = any(s.status == StageStatus.RUNNING for s in self.stages)
        if has_running:
            self._spinner_frame = (self._spinner_frame + 1) % 8
            self._update_display()

    def _get_icon(self, status: StageStatus) -> str:
        """Get status icon."""
        if status == StageStatus.PENDING:
            return "[#5C5C5C]○[/]"
        elif status == StageStatus.RUNNING:
            frames = ["◐", "◓", "◑", "◒"]
            return f"[#9370DB]{frames[self._spinner_frame % 4]}[/]"
        elif status == StageStatus.COMPLETE:
            return "[#00FF7F]✓[/]"
        else:  # ERROR
            return "[#FF6B6B]✗[/]"

    def _get_label_style(self, status: StageStatus) -> str:
        """Get label style for status."""
        if status == StageStatus.PENDING:
            return "#5C5C5C"
        elif status == StageStatus.RUNNING:
            return "bold white"
        elif status == StageStatus.COMPLETE:
            return "#8B8B8B"
        else:  # ERROR
            return "#FF6B6B"

    def _update_display(self) -> None:
        """Rebuild the stages display."""
        lines = []
        for i, stage in enumerate(self.stages):
            icon = self._get_icon(stage.status)
            style = self._get_label_style(stage.status)
            label = f"[{style}]Stage {i}: {stage.name}[/]"

            # Add detail for running/complete stages
            detail = ""
            if stage.detail:
                detail = f" [{style}]({stage.detail})[/]"
            elif stage.status == StageStatus.RUNNING and stage.progress is not None:
                detail = f" [{style}]({stage.progress}%)[/]"

            lines.append(f"  {icon} {label}{detail}")

        display = self.query_one("#stages-display", Static)
        display.update("\n".join(lines))

    def watch_stages(self, stages: List[Stage]) -> None:
        """React to stages change."""
        self._update_display()

    def update_stage(
        self,
        index: int,
        status: Optional[StageStatus] = None,
        progress: Optional[int] = None,
        detail: Optional[str] = None
    ) -> None:
        """Update a specific stage."""
        if 0 <= index < len(self.stages):
            stage = self.stages[index]
            if status is not None:
                stage.status = status
            if progress is not None:
                stage.progress = progress
            if detail is not None:
                stage.detail = detail
            self._update_display()

    def set_stage_running(self, index: int) -> None:
        """Mark a stage as running."""
        self.update_stage(index, status=StageStatus.RUNNING)

    def set_stage_complete(self, index: int, detail: str = "") -> None:
        """Mark a stage as complete."""
        self.update_stage(index, status=StageStatus.COMPLETE, detail=detail)

    def set_stage_error(self, index: int, detail: str = "") -> None:
        """Mark a stage as errored."""
        self.update_stage(index, status=StageStatus.ERROR, detail=detail)

    def reset(self) -> None:
        """Reset all stages to pending."""
        for stage in self.stages:
            stage.status = StageStatus.PENDING
            stage.progress = None
            stage.detail = ""
        self._update_display()
