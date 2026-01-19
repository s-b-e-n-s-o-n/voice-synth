#!/usr/bin/env python3
"""
Simple TUI for Voice Synthesizer using questionary + rich.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

# Add script dir to path for pipeline import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

console = Console()

# Custom style matching the purple/green aesthetic
custom_style = Style([
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#00ff7f bold'),
    ('pointer', 'fg:#673ab7 bold'),
    ('highlighted', 'fg:#673ab7 bold'),
    ('selected', 'fg:#00ff7f'),
])

# Paths
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "voice-synth"
JOBS_FILE = CACHE_DIR / "jobs.json"
VERSION = "0.3.1-alpha"


def clear_screen():
    """Clear terminal screen."""
    console.clear()


def show_header():
    """Display the app header."""
    console.print()
    console.print(Panel(
        "[bold #673ab7]Voice Synthesizer[/]\n"
        "[dim]Email data preparation for GPT fine-tuning[/]\n"
        f"[dim italic]v{VERSION}[/]",
        border_style="#673ab7",
        padding=(1, 4),
    ))
    console.print()


def clean_path(raw_path: str) -> str:
    """Clean drag-and-drop path."""
    path = raw_path.strip()
    if (path.startswith("'") and path.endswith("'")) or \
       (path.startswith('"') and path.endswith('"')):
        path = path[1:-1]
    path = path.replace("\\ ", " ")
    if path.startswith("file://"):
        from urllib.parse import unquote
        path = unquote(path[7:])
    return os.path.expanduser(path).strip()


# =============================================================================
# Job Tracking
# =============================================================================

def load_jobs():
    """Load jobs from file."""
    if not JOBS_FILE.exists():
        return []
    try:
        return json.loads(JOBS_FILE.read_text())
    except:
        return []


def save_job(mbox_path: str, work_dir: str, status: str, sender: Optional[str] = None):
    """Save a job."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = load_jobs()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update existing or add new
    found = False
    for job in jobs:
        if job.get('mbox') == mbox_path and job.get('work_dir') == work_dir:
            job['status'] = status
            job['updated'] = timestamp
            if sender:
                job['sender'] = sender
            found = True
            break

    if not found:
        jobs.append({
            'mbox': mbox_path,
            'work_dir': work_dir,
            'status': status,
            'started': timestamp,
            'updated': timestamp,
            'sender': sender,
        })

    # Keep last 10
    jobs.sort(key=lambda x: x.get('updated', ''), reverse=True)
    jobs = jobs[:10]

    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


def get_incomplete_job():
    """Get most recent incomplete job."""
    for job in load_jobs():
        if job.get('status') != 'in_progress':
            continue
        work_dir = job.get('work_dir', '')
        if not os.path.isdir(work_dir):
            continue
        # Check for intermediate files
        if os.path.exists(os.path.join(work_dir, 'style_shortlist.csv')):
            continue
        if any(os.path.exists(os.path.join(work_dir, f))
               for f in ['emails_raw.json', 'emails.jsonl', 'cleaned_emails.json']):
            return job
    return None


def mark_job_complete(work_dir: str):
    """Mark jobs in work_dir as complete."""
    jobs = load_jobs()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for job in jobs:
        if job.get('work_dir') == work_dir:
            job['status'] = 'completed'
            job['updated'] = timestamp
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


# =============================================================================
# Pipeline Screens
# =============================================================================

def pick_file() -> Optional[str]:
    """File picker screen."""
    clear_screen()
    show_header()

    console.print("[bold #673ab7]Select Input File[/]")
    console.print("[dim]Drop your Google Takeout export (.mbox, folder, or .zip)[/]")
    console.print("[dim italic]Drag from Finder into this window, then press Enter[/]")
    console.print()

    raw_path = questionary.text(
        "File path:",
        style=custom_style,
    ).ask()

    if raw_path is None:  # Ctrl+C
        return None

    path = clean_path(raw_path)

    if not os.path.exists(path):
        console.print(f"[red]File not found: {path}[/]")
        questionary.press_any_key_to_continue(style=custom_style).ask()
        return pick_file()

    return os.path.abspath(path)


def pick_sender(input_file: str) -> Optional[str]:
    """Sender filter screen with auto-detection."""
    clear_screen()
    show_header()

    console.print("[bold #673ab7]Sender Filter[/]")
    console.print("[dim]Filter to emails you wrote (not received)[/]")
    console.print()

    # Try to detect owner email
    detected = None
    try:
        from pipeline import detect_owner_email
        with console.status("[#673ab7]Detecting your email address...[/]"):
            detected = detect_owner_email(input_file)
    except:
        pass

    if detected:
        console.print(f"[green]Detected: {detected}[/]")
        console.print()

        choice = questionary.select(
            "Use this email?",
            choices=[
                f"Yes, use {detected}",
                "Enter a different email",
                "No filter (keep all senders)",
            ],
            style=custom_style,
        ).ask()

        if choice is None:
            return None
        if choice.startswith("Yes"):
            return detected
        elif choice.startswith("Enter"):
            return questionary.text("Email address:", default=detected, style=custom_style).ask()
        else:
            return ""
    else:
        console.print("[dim]Could not auto-detect email.[/]")
        console.print()

        choice = questionary.select(
            "Filter by sender?",
            choices=[
                "Enter email address",
                "No filter (keep all senders)",
            ],
            style=custom_style,
        ).ask()

        if choice is None:
            return None
        if choice.startswith("Enter"):
            return questionary.text("Email address:", style=custom_style).ask()
        return ""


def run_pipeline(input_file: str, sender: Optional[str], work_dir: str) -> Optional[dict]:
    """Run the pipeline with progress display."""
    clear_screen()
    show_header()

    console.print("[bold #673ab7]Processing Emails[/]")
    console.print("[dim italic]This may take a few minutes for large mailboxes[/]")
    console.print()

    # Save job
    save_job(input_file, work_dir, "in_progress", sender)

    original_dir = os.getcwd()
    os.chdir(work_dir)

    try:
        from pipeline import (
            import_mbox, convert_to_jsonl, clean_emails, build_shortlist,
            needs_mbox_import
        )

        results = {}

        with Progress(
            SpinnerColumn(style="#673ab7"),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:

            # Stage 0: Import
            if needs_mbox_import(input_file):
                task = progress.add_task("Importing MBOX...", total=None)
                results["import"] = import_mbox(input_file, "emails_raw.json", quiet=True)
                progress.update(task, description=f"[green]✓[/] Imported {results['import'].get('imported', 0):,} emails")
                progress.stop_task(task)
                input_file = "emails_raw.json"

            # Stage 1: Convert
            task = progress.add_task("Converting to JSONL...", total=None)
            results["convert"] = convert_to_jsonl(input_file, "emails.jsonl", quiet=True)
            progress.update(task, description=f"[green]✓[/] Converted {results['convert'].get('kept', 0):,} records")
            progress.stop_task(task)

            # Stage 2: Clean
            task = progress.add_task("Cleaning & anonymizing...", total=None)
            results["clean"] = clean_emails("emails.jsonl", "cleaned_emails.json", sender or None, quiet=True)
            progress.update(task, description=f"[green]✓[/] Cleaned {results['clean'].get('kept', 0):,} emails")
            progress.stop_task(task)

            # Stage 3: Curate
            task = progress.add_task("Curating shortlist...", total=None)
            results["curate"] = build_shortlist("cleaned_emails.json", "style_shortlist.csv", quiet=True)
            progress.update(task, description=f"[green]✓[/] Selected {results['curate'].get('shortlisted', 0):,} emails")
            progress.stop_task(task)

        # Copy to Desktop
        desktop = Path.home() / "Desktop" / "style_shortlist.csv"
        try:
            shutil.copy("style_shortlist.csv", desktop)
            results["desktop_path"] = str(desktop)
        except:
            results["desktop_path"] = os.path.abspath("style_shortlist.csv")

        mark_job_complete(work_dir)
        return results

    except Exception as e:
        console.print(f"\n[red]Error: {e}[/]")
        questionary.press_any_key_to_continue(style=custom_style).ask()
        return None

    finally:
        os.chdir(original_dir)


def show_results(results: dict):
    """Display pipeline results."""
    clear_screen()
    show_header()

    console.print("[bold green]Processing Complete![/]")
    console.print()

    # Output path
    desktop_path = results.get("desktop_path", "style_shortlist.csv")
    if "Desktop" in str(desktop_path):
        console.print("[green]Output saved to: ~/Desktop/style_shortlist.csv[/]")
    else:
        console.print(f"[green]Output saved to: {desktop_path}[/]")
    console.print()

    # Results table
    table = Table(border_style="#673ab7")
    table.add_column("Stage", style="bold")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Filtered", justify="right")

    if "import" in results:
        imp = results["import"]
        table.add_row("Import", f"{imp.get('total', 0):,}", f"{imp.get('imported', 0):,}", f"{imp.get('skipped', 0):,}")

    if "convert" in results:
        conv = results["convert"]
        table.add_row("Convert", f"{conv.get('total', 0):,}", f"{conv.get('kept', 0):,}", f"{conv.get('total', 0) - conv.get('kept', 0):,}")

    if "clean" in results:
        clean = results["clean"]
        table.add_row("Clean", f"{clean.get('total', 0):,}", f"{clean.get('kept', 0):,}", f"{clean.get('total', 0) - clean.get('kept', 0):,}")

    if "curate" in results:
        curate = results["curate"]
        table.add_row("Curate", f"{curate.get('total_input', 0):,}", f"[bold green]{curate.get('shortlisted', 0):,}[/]", f"{curate.get('total_input', 0) - curate.get('shortlisted', 0):,}")

    console.print(table)
    console.print()
    console.print("[dim italic]Open the CSV in a spreadsheet to review your emails[/]")
    console.print()

    questionary.press_any_key_to_continue(style=custom_style).ask()


def show_help():
    """Display help."""
    clear_screen()
    show_header()

    console.print("""[bold #673ab7]Pipeline Stages[/]

[bold]0. Import[/]   - Import MBOX from Google Takeout, strip attachments
[bold]1. Convert[/]  - Convert JSON to JSONL, filter unsafe fields
[bold]2. Clean[/]    - Anonymize PII with Presidio, remove signatures
[bold]3. Curate[/]   - Score by richness, group by topic, output CSV

[bold #673ab7]Quick Start[/]

1. Go to [link]https://takeout.google.com[/link]
2. Select [bold]only Mail[/] → Export as [bold]MBOX[/]
3. Run this tool and select your .mbox file
4. Enter your email to filter to emails [bold]you wrote[/]
5. Review style_shortlist.csv in a spreadsheet

[bold #673ab7]CLI Usage[/]

[dim]./voice-synth run <file> --sender <email>[/]

[bold #673ab7]Files[/]

Dependencies: ~/.cache/voice-synth/venv/
""")

    questionary.press_any_key_to_continue(style=custom_style).ask()


def do_uninstall():
    """Uninstall dialog."""
    clear_screen()
    show_header()

    console.print("[bold #673ab7]Uninstall[/]")
    console.print()
    console.print(f"This will delete: [dim]{CACHE_DIR}[/]")
    console.print()

    if questionary.confirm("Delete everything and uninstall?", default=False, style=custom_style).ask():
        try:
            if CACHE_DIR.exists():
                shutil.rmtree(CACHE_DIR)
            console.print("[green]✓ Uninstalled successfully[/]")
            console.print("[dim]Run ./voice-synth to reinstall.[/]")
            sys.exit(0)
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")

    questionary.press_any_key_to_continue(style=custom_style).ask()


# =============================================================================
# Main Menu
# =============================================================================

def main_menu():
    """Main menu loop."""
    while True:
        clear_screen()
        show_header()

        # Check for incomplete jobs
        incomplete = get_incomplete_job()

        choices = []
        if incomplete:
            mbox_name = os.path.basename(incomplete.get('mbox', 'unknown'))
            choices.append(f"Continue previous ({mbox_name})")
        choices.extend(["Get started", "Help", "Uninstall", "Quit"])

        choice = questionary.select(
            "What would you like to do?",
            choices=choices,
            style=custom_style,
        ).ask()

        if choice is None or choice == "Quit":
            console.print("\n[dim]Goodbye![/]\n")
            break

        elif choice.startswith("Continue"):
            # Resume incomplete job
            work_dir = incomplete.get('work_dir', os.getcwd())
            input_file = incomplete.get('mbox', '')
            sender = incomplete.get('sender', '')

            os.chdir(work_dir)
            results = run_pipeline(input_file, sender, work_dir)
            if results:
                show_results(results)

        elif choice == "Get started":
            input_file = pick_file()
            if input_file is None:
                continue

            sender = pick_sender(input_file)
            if sender is None:
                continue

            work_dir = os.getcwd()
            results = run_pipeline(input_file, sender, work_dir)
            if results:
                show_results(results)

        elif choice == "Help":
            show_help()

        elif choice == "Uninstall":
            do_uninstall()


def main():
    """Entry point."""
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/]\n")


if __name__ == "__main__":
    main()
