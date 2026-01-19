"""Job tracking for resumable pipeline runs."""

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


@dataclass
class Job:
    """A tracked pipeline job."""
    mbox: str
    work_dir: str
    status: str  # "in_progress" or "completed"
    started: str
    updated: str
    sender: Optional[str] = None

    @property
    def mbox_name(self) -> str:
        """Get just the filename of the mbox."""
        return os.path.basename(self.mbox)

    @property
    def has_intermediate_files(self) -> bool:
        """Check if work_dir has intermediate files."""
        if not os.path.isdir(self.work_dir):
            return False
        return any(
            os.path.exists(os.path.join(self.work_dir, f))
            for f in ["emails_raw.json", "emails.jsonl", "cleaned_emails.json"]
        )

    @property
    def is_completed(self) -> bool:
        """Check if job has final output."""
        return os.path.exists(os.path.join(self.work_dir, "style_shortlist.csv"))

    @property
    def resume_stage(self) -> Optional[str]:
        """Determine which stage to resume from."""
        if not os.path.isdir(self.work_dir):
            return None
        if os.path.exists(os.path.join(self.work_dir, "cleaned_emails.json")):
            return "curate"
        elif os.path.exists(os.path.join(self.work_dir, "emails.jsonl")):
            return "clean"
        elif os.path.exists(os.path.join(self.work_dir, "emails_raw.json")):
            return "convert"
        return None


class JobTracker:
    """Manages job tracking in ~/.cache/voice-synth/jobs.json."""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_home = os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
            cache_dir = Path(cache_home) / "voice-synth"
        self.cache_dir = Path(cache_dir)
        self.jobs_file = self.cache_dir / "jobs.json"

    def _ensure_file(self) -> None:
        """Ensure jobs file exists."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.jobs_file.exists():
            self.jobs_file.write_text("[]")

    def _load_jobs(self) -> List[Job]:
        """Load jobs from file."""
        self._ensure_file()
        try:
            data = json.loads(self.jobs_file.read_text())
            return [Job(**j) for j in data]
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_jobs(self, jobs: List[Job]) -> None:
        """Save jobs to file."""
        self._ensure_file()
        data = [asdict(j) for j in jobs]
        self.jobs_file.write_text(json.dumps(data, indent=2))

    def save_job(
        self,
        mbox_path: str,
        work_dir: str,
        status: str,
        sender: Optional[str] = None
    ) -> None:
        """Add or update a job."""
        jobs = self._load_jobs()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Find existing job
        existing = None
        for job in jobs:
            if job.mbox == mbox_path and job.work_dir == work_dir:
                existing = job
                break

        if existing:
            existing.status = status
            existing.updated = timestamp
            if sender:
                existing.sender = sender
        else:
            jobs.append(Job(
                mbox=mbox_path,
                work_dir=work_dir,
                status=status,
                started=timestamp,
                updated=timestamp,
                sender=sender
            ))

        # Keep only last 10 jobs, sorted by update time
        jobs.sort(key=lambda x: x.updated, reverse=True)
        jobs = jobs[:10]

        self._save_jobs(jobs)

    def get_incomplete_jobs(self) -> List[Job]:
        """Get jobs that are in_progress and resumable."""
        jobs = self._load_jobs()
        incomplete = []

        for job in jobs:
            if job.status != "in_progress":
                continue
            if not os.path.isdir(job.work_dir):
                continue
            if job.is_completed:
                continue
            if job.has_intermediate_files:
                incomplete.append(job)

        return incomplete

    def get_most_recent_incomplete(self) -> Optional[Job]:
        """Get the most recent incomplete job."""
        incomplete = self.get_incomplete_jobs()
        return incomplete[0] if incomplete else None

    def mark_completed(self, work_dir: str) -> None:
        """Mark any job in the given work_dir as completed."""
        jobs = self._load_jobs()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for job in jobs:
            if job.work_dir == work_dir:
                job.status = "completed"
                job.updated = timestamp

        self._save_jobs(jobs)

    def clear_all(self) -> None:
        """Clear all tracked jobs."""
        self._save_jobs([])
