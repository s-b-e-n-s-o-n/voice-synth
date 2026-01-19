#!/usr/bin/env python3
"""
pipeline.py
-----------
Voice Synthesizer - Email data preparation pipeline for fine-tuning GPT models.

This module provides functions for:
0. Importing MBOX files (from Google Takeout) to JSON
1. Converting JSON to JSONL (with attachment stripping)
2. Cleaning and anonymizing emails (using Microsoft Presidio)
3. Curating high-quality style samples

Can be used as a library or run directly with subcommands.
"""

import argparse
import csv
import hashlib
import json
import mailbox
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from email import policy
from email.utils import getaddresses, parseaddr
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# =============================================================================
# STAGE 0: MBOX IMPORT (Google Takeout)
# =============================================================================

def extract_body_from_message(msg) -> Tuple[str, str]:
    """
    Extract plain text and HTML body from an email message.
    Handles multipart messages, skipping attachments.

    Returns:
        Tuple of (plain_text, html_text)
    """
    plain_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue

                # Try to decode the payload
                charset = part.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("utf-8", errors="replace")

                if content_type == "text/plain" and not plain_body:
                    plain_body = text
                elif content_type == "text/html" and not html_body:
                    html_body = text

            except Exception:
                continue
    else:
        # Single part message
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("utf-8", errors="replace")

                if msg.get_content_type() == "text/html":
                    html_body = text
                else:
                    plain_body = text
        except Exception:
            pass

    return plain_body, html_body


def find_mbox_files(input_path: str, quiet: bool = False) -> List[str]:
    """
    Find all MBOX files from a path (file, directory, or zip).

    Args:
        input_path: Path to MBOX file, directory, or zip file
        quiet: If True, suppress progress output

    Returns:
        List of paths to MBOX files
    """
    import glob
    import tempfile
    import zipfile

    input_path = os.path.abspath(input_path)

    # Case 1: Single MBOX file
    if os.path.isfile(input_path) and input_path.lower().endswith('.mbox'):
        if not quiet:
            print(f"📄 Found single MBOX file")
        return [input_path]

    # Case 2: ZIP file (Google Takeout export)
    if os.path.isfile(input_path) and input_path.lower().endswith('.zip'):
        if not quiet:
            print(f"📦 Extracting ZIP file: {os.path.basename(input_path)}")

        # Extract to a directory next to the zip
        extract_dir = input_path.rsplit('.', 1)[0] + "_extracted"
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(input_path, 'r') as zf:
            zf.extractall(extract_dir)

        if not quiet:
            print(f"📂 Extracted to: {extract_dir}")

        # Now search the extracted directory
        input_path = extract_dir

    # Case 3: Directory - glob for all MBOX files
    if os.path.isdir(input_path):
        mbox_files = glob.glob(os.path.join(input_path, '**', '*.mbox'), recursive=True)
        mbox_files.sort()  # Consistent ordering

        if not quiet:
            if len(mbox_files) == 0:
                print(f"⚠️  No .mbox files found in: {input_path}")
            elif len(mbox_files) == 1:
                print(f"📄 Found 1 MBOX file in directory")
            else:
                print(f"📚 Found {len(mbox_files)} MBOX files:")
                for f in mbox_files:
                    rel_path = os.path.relpath(f, input_path)
                    size_mb = os.path.getsize(f) / (1024 * 1024)
                    print(f"   └── {rel_path} ({size_mb:.1f} MB)")

        return mbox_files

    # Fallback: treat as single file path
    if os.path.isfile(input_path):
        if not quiet:
            print(f"📄 Using file: {os.path.basename(input_path)}")
        return [input_path]

    return []


def import_mbox_single(
    input_path: str,
    quiet: bool = False,
    max_age_years: int = 5
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Import a single MBOX file to a list of email dicts.

    Returns:
        Tuple of (emails_list, stats_dict)
    """
    from email.utils import parsedate_to_datetime

    mbox = mailbox.mbox(input_path)
    emails = []
    total = 0
    skipped = 0
    spam_trash = 0
    too_old = 0

    # Calculate cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_years * 365)

    for message in mbox:
        total += 1

        if not quiet and total % 500 == 0:
            print(f"      Processed {total} messages...")

        try:
            # Gmail-specific: get labels early to filter spam/trash
            labels = message.get("X-Gmail-Labels", "")
            label_list = [l.strip().lower() for l in labels.split(",")]

            # Skip spam, trash, and drafts
            if "spam" in label_list or "trash" in label_list or "draft" in label_list or "drafts" in label_list:
                spam_trash += 1
                continue

            # Extract headers
            msg_id = message.get("Message-ID", "")
            from_addr = message.get("From", "")
            to_addr = message.get("To", "")
            cc_addr = message.get("Cc", "")
            subject = message.get("Subject", "")
            date = message.get("Date", "")

            # Filter by age early
            if date:
                try:
                    msg_date = parsedate_to_datetime(date)
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    if msg_date < cutoff_date:
                        too_old += 1
                        continue
                except Exception:
                    pass  # If date parsing fails, keep the message

            # Extract body (skipping attachments)
            plain_body, html_body = extract_body_from_message(message)

            # Prefer plain text, fall back to HTML
            body = plain_body if plain_body.strip() else html_body

            if not body.strip() and not subject.strip():
                skipped += 1
                continue

            emails.append({
                "Message-ID": msg_id,
                "From": from_addr,
                "To": to_addr,
                "Cc": cc_addr,
                "Subject": subject,
                "Date": date,
                "Body": body,
                "X-Gmail-Labels": labels,
            })

        except Exception as e:
            if not quiet:
                print(f"      Warning: Failed to parse message {total}: {e}")
            skipped += 1
            continue

    mbox.close()

    return emails, {"total": total, "imported": len(emails), "skipped": skipped, "spam_trash": spam_trash, "too_old": too_old}


def import_mbox(
    input_path: str,
    output_path: Optional[str] = None,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Import MBOX file(s) from a path (file, directory, or zip) to JSON.
    Strips attachments, keeps only text content.

    Supports:
    - Single .mbox file
    - Directory containing .mbox files (searches recursively)
    - .zip file (Google Takeout export - extracts and finds .mbox files)

    Args:
        input_path: Path to MBOX file, directory, or zip file
        output_path: Path to output JSON file (default: emails_raw.json)
        quiet: If True, suppress progress output

    Returns:
        Statistics dict
    """
    if output_path is None:
        if os.path.isfile(input_path) and input_path.lower().endswith('.mbox'):
            base = input_path.rsplit(".", 1)[0]
            output_path = base + ".json"
        else:
            output_path = "emails_raw.json"

    if not quiet:
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING EMAILS")
        print(f"{'='*60}")

    # Find all MBOX files
    mbox_files = find_mbox_files(input_path, quiet=quiet)

    if not mbox_files:
        if not quiet:
            print(f"\n❌ No MBOX files found!")
            print(f"\n📋 INSTRUCTIONS:")
            print(f"   1. Go to https://takeout.google.com")
            print(f"   2. Select only 'Mail' and click 'Next'")
            print(f"   3. Choose file size: 50 GB (to avoid splitting)")
            print(f"   4. Download and either:")
            print(f"      • Point to the .zip file directly")
            print(f"      • Extract it and point to the folder")
            print(f"      • Point to a specific .mbox file")
            print(f"\n   Examples:")
            print(f"      python pipeline.py run takeout.zip --sender you@gmail.com")
            print(f"      python pipeline.py run ./Takeout/ --sender you@gmail.com")
            print(f"      python pipeline.py run 'All mail.mbox' --sender you@gmail.com")
        return {"total": 0, "imported": 0, "skipped": 0, "files": 0, "output": output_path}

    # Import all MBOX files
    all_emails = []
    total_stats = {"total": 0, "imported": 0, "skipped": 0, "spam_trash": 0, "files": len(mbox_files)}

    for i, mbox_path in enumerate(mbox_files, 1):
        if not quiet:
            rel_name = os.path.basename(mbox_path)
            if len(mbox_files) > 1:
                print(f"\n   📄 [{i}/{len(mbox_files)}] {rel_name}")
            else:
                print(f"\n   📄 {rel_name}")

        emails, stats = import_mbox_single(mbox_path, quiet=quiet)
        all_emails.extend(emails)

        total_stats["total"] += stats["total"]
        total_stats["imported"] += stats["imported"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["spam_trash"] += stats["spam_trash"]

        if not quiet:
            msg = f"      ✓ {stats['imported']} emails imported"
            if stats["spam_trash"] > 0:
                msg += f" (🗑️ {stats['spam_trash']} spam/trash/drafts filtered)"
            print(msg)

    if not quiet:
        print(f"\n{'─'*60}")
        if len(mbox_files) > 1:
            print(f"📊 TOTAL: {total_stats['imported']} emails from {len(mbox_files)} files")
        else:
            print(f"📊 TOTAL: {total_stats['imported']} emails")
        if total_stats["spam_trash"] > 0:
            print(f"🗑️ Filtered: {total_stats['spam_trash']} spam/trash/drafts")
        print(f"💾 Saving to: {output_path}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_emails, f, ensure_ascii=False, indent=2)

    total_stats["output"] = output_path
    return total_stats


def detect_owner_email(input_path: str, sample_size: int = 50) -> Optional[str]:
    """
    Detect the mailbox owner's email from an mbox file.

    Uses the "Delivered-To" header which Gmail sets to indicate the actual
    mailbox recipient - much more reliable than looking at From addresses.

    Args:
        input_path: Path to mbox file
        sample_size: Unused - we just grab the first match (instant)

    Returns:
        Owner's email address, or None if not detected
    """
    import re

    mbox_files = find_mbox_files(input_path, quiet=True)
    if not mbox_files:
        return None

    # Just read first few KB to find Delivered-To header - nearly instant
    for mbox_path in mbox_files:
        try:
            with open(mbox_path, "r", encoding="utf-8", errors="ignore") as f:
                chunk = f.read(8192)  # First 8KB has the headers
                match = re.search(r"^Delivered-To:\s*(.+)$", chunk, re.MULTILINE | re.IGNORECASE)
                if match:
                    _, email = parseaddr(match.group(1).strip())
                    if email:
                        return email.lower()
        except Exception:
            continue

    return None


# =============================================================================
# STAGE 1: FORMAT CONVERSION
# =============================================================================

SAFE_FIELDS: Set[str] = {
    "Subject", "subject",
    "Body", "body", "Text", "text", "Content", "content",
    "From", "from", "Sender", "sender", "emailFrom", "email_from",
    "To", "to", "Recipient", "recipient", "Recipients", "recipients",
    "Cc", "cc", "CC",
    "Bcc", "bcc", "BCC",
    "Date", "date", "sent", "sentAt", "created_at", "createdAt",
    "Message-ID", "Message-Id", "MessageId", "message_id", "messageId",
    "Auto-Submitted", "auto-submitted",
    "X-Autoreply", "x-autoreply",
    "X-Auto-Response-Suppress", "x-auto-response-suppress",
    "Precedence", "precedence",
    "Reply-To", "reply-to", "replyTo",
}

BLOCKED_FIELDS: Set[str] = {
    "attachments", "Attachments", "files", "Files", "media", "Media",
    "images", "Images", "inline_images", "inlineImages",
    "raw", "Raw", "mimeContent", "mime_content", "payload", "Payload",
    "X-Originating-IP", "x-originating-ip", "Received", "received",
    "X-Mailer", "x-mailer", "X-Original-To", "x-original-to",
    "Delivered-To", "delivered-to", "Return-Path", "return-path",
}


def filter_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a record to only include safe fields, removing attachments."""
    filtered = {}
    for key, value in record.items():
        if key in BLOCKED_FIELDS or key not in SAFE_FIELDS:
            continue
        if value is None:
            continue
        if isinstance(value, str) and len(value) > 1000:
            sample = value[:100]
            if not any(c in sample for c in [' ', '\n', '.', ',']):
                continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if any(k in value[0] for k in ['filename', 'content', 'data', 'base64']):
                continue
        filtered[key] = value
    return filtered


def convert_to_jsonl(
    input_path: str,
    output_path: Optional[str] = None,
    strip_fields: bool = True,
    quiet: bool = False
) -> Dict[str, int]:
    """
    Convert JSON array to JSONL format, optionally stripping attachments.

    Args:
        input_path: Path to input JSON file
        output_path: Path to output JSONL file (default: input with .jsonl extension)
        strip_fields: If True, apply field whitelist filtering
        quiet: If True, suppress progress output

    Returns:
        Statistics dict with counts
    """
    try:
        import ijson
    except ImportError:
        print("Error: ijson not installed. Run: pip install ijson")
        sys.exit(1)

    if output_path is None:
        if input_path.endswith(".json"):
            output_path = input_path[:-5] + ".jsonl"
        else:
            output_path = input_path + ".jsonl"

    total = kept = 0

    if not quiet:
        print(f"   📂 Reading: {os.path.basename(input_path)}")

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for record in ijson.items(fin, "item"):
            total += 1
            if strip_fields:
                record = filter_record(record)
            if not record:
                continue
            json.dump(record, fout, ensure_ascii=False)
            fout.write("\n")
            kept += 1
            if not quiet and total % 2000 == 0:
                print(f"      ⏳ {total:,} records processed...")

    if not quiet:
        print(f"   ✓ Converted {kept:,} records")
        print(f"   💾 Saved to: {os.path.basename(output_path)}")

    return {"total": total, "kept": kept, "output": output_path}


# =============================================================================
# STAGE 2: CLEANING & PII ANONYMIZATION
# =============================================================================

_analyzer = None
_anonymizer = None


def get_analyzer():
    """Lazy initialization of Presidio analyzer."""
    global _analyzer
    if _analyzer is None:
        try:
            from presidio_analyzer import AnalyzerEngine
            _analyzer = AnalyzerEngine()
        except ImportError:
            print("Error: presidio-analyzer not installed.")
            print("Run: pip install presidio-analyzer presidio-anonymizer")
            print("Then: python -m spacy download en_core_web_lg")
            sys.exit(1)
    return _analyzer


def get_anonymizer():
    """Lazy initialization of Presidio anonymizer."""
    global _anonymizer
    if _anonymizer is None:
        from presidio_anonymizer import AnonymizerEngine
        _anonymizer = AnonymizerEngine()
    return _anonymizer


PII_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
    "US_SSN", "US_PASSPORT", "US_DRIVER_LICENSE", "IP_ADDRESS", "URL", "LOCATION",
]


def get_operators():
    """Get Presidio operators for anonymization."""
    from presidio_anonymizer.entities import OperatorConfig
    return {
        "PERSON": OperatorConfig("replace", {"new_value": "[PERSON]"}),
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
        "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
        "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CREDIT_CARD]"}),
        "US_SSN": OperatorConfig("replace", {"new_value": "[SSN]"}),
        "US_PASSPORT": OperatorConfig("replace", {"new_value": "[PASSPORT]"}),
        "US_DRIVER_LICENSE": OperatorConfig("replace", {"new_value": "[LICENSE]"}),
        "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP]"}),
        "URL": OperatorConfig("replace", {"new_value": "[URL]"}),
        "LOCATION": OperatorConfig("replace", {"new_value": "[LOCATION]"}),
        "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
    }


def anonymize_pii(text: str, score_threshold: float = 0.4) -> str:
    """Detect and anonymize PII in text using Presidio."""
    if not text or not text.strip():
        return text
    analyzer = get_analyzer()
    anonymizer = get_anonymizer()
    results = analyzer.analyze(
        text=text, entities=PII_ENTITIES, language="en", score_threshold=score_threshold
    )
    if not results:
        return text
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results, operators=get_operators())
    return anonymized.text


# Regex patterns for email-specific cleaning
QUOTED_REPLY_RE = re.compile(r'^(On .+ wrote:|From:|Sent:|To:|Subject:|-----Original Message-----)', re.IGNORECASE)
QUOTE_MARK_RE = re.compile(r'^\s*>', re.MULTILINE)
SIG_SEP_RE = re.compile(r'^(--\s*$|—\s*$|___+\s*$)', re.MULTILINE | re.IGNORECASE)
SIG_FOOT_RE = re.compile(
    r'^(Sent from my iPhone.*$|Sent from my iPad.*$|Get Outlook for.*$|'
    r'Please consider the environment.*$|This message.*confidential.*$)',
    re.MULTILINE | re.IGNORECASE
)
UNSUB_RE = re.compile(r'unsubscribe|manage your preferences|update preferences', re.IGNORECASE)
HTML_TAG_RE = re.compile(r'<[^>]+>')

AUTO_SUBJECT_KEYWORDS = [
    "out of office", "ooo", "automatic reply", "auto-reply", "autoreply",
    "away from the office", "on vacation", "out of the office",
    "has accepted this invitation", "has declined this invitation",
]


def strip_html(text: str) -> str:
    return HTML_TAG_RE.sub("", text)


def remove_quoted_replies(t: str) -> str:
    lines = t.splitlines()
    out = []
    for line in lines:
        if QUOTED_REPLY_RE.match(line):
            break
        if QUOTE_MARK_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out).strip()


def remove_signatures(t: str) -> str:
    t = SIG_FOOT_RE.sub("", t)
    sep = None
    for m in SIG_SEP_RE.finditer(t):
        sep = m
    if sep:
        t = t[:sep.start()].rstrip()
    unsub = UNSUB_RE.search(t)
    if unsub:
        t = t[:unsub.start()].rstrip()
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def cleanse_body(t: str) -> str:
    if not t:
        return ""
    t = strip_html(t)
    t = remove_quoted_replies(t)
    t = remove_signatures(t)
    t = anonymize_pii(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def cleanse_subject(t: str) -> str:
    if not t:
        return ""
    return anonymize_pii(strip_html(t)).strip()


def cleanse_to_field(t: str) -> str:
    if not t:
        return ""
    parsed = getaddresses([t])
    rebuilt = []
    for display, addr in parsed:
        if display:
            display = anonymize_pii(display)
        if addr:
            addr = anonymize_pii(addr)
        if display and addr:
            rebuilt.append(f"{display} <{addr}>")
        elif addr:
            rebuilt.append(addr)
        elif display:
            rebuilt.append(display)
    return ", ".join(rebuilt)


def parse_date_any(d: Optional[str]) -> Optional[datetime]:
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(str(d).replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(str(d))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def get_field(rec: Dict[str, Any], *keys: str):
    """Case-insensitive field lookup."""
    if not isinstance(rec, dict):
        return None
    lowered = {k.lower(): v for k, v in rec.items()}
    for key in keys:
        if key in rec and rec[key]:
            return rec[key]
        if key.lower() in lowered and lowered[key.lower()]:
            return lowered[key.lower()]
    return None


def is_auto_reply(rec: Dict[str, Any], subject: str, body: str) -> bool:
    s = (subject or "").lower()
    if any(k in s for k in AUTO_SUBJECT_KEYWORDS):
        return True
    b = (body or "").lower()
    if any(phrase in b for phrase in [
        "i am currently out of the office", "i am out of office until",
        "this is an automatic reply", "this is an auto-reply"
    ]):
        return True
    auto_submitted = get_field(rec, "Auto-Submitted", "auto-submitted")
    if auto_submitted and str(auto_submitted).lower() not in ("no", "none"):
        return True
    return False


def iter_records(path: str) -> Iterable[Dict[str, Any]]:
    """Iterate over JSON array or JSONL file."""
    with open(path, "r", encoding="utf-8") as f:
        first = f.read(1)
        f.seek(0)
        if first == "[":
            data = json.load(f)
            for rec in data:
                if isinstance(rec, dict):
                    yield rec
        else:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        yield rec
                except Exception:
                    continue


def clean_emails(
    input_path: str,
    output_path: str = "cleaned_emails.json",
    sender_email: Optional[str] = None,
    years: int = 5,
    quiet: bool = False
) -> Dict[str, int]:
    """
    Clean and anonymize emails using Presidio.

    Args:
        input_path: Path to input JSON or JSONL file
        output_path: Path to output JSON file
        sender_email: Only keep emails from this sender (None = keep all)
        years: Only keep emails from the past N years
        quiet: If True, suppress progress output

    Returns:
        Statistics dict
    """
    cutoff = datetime.utcnow().replace(year=datetime.utcnow().year - years)
    stats = {"total": 0, "kept": 0, "skipped_sender": 0, "skipped_date": 0, "skipped_auto": 0, "skipped_empty": 0}
    results: List[Dict[str, Any]] = []

    if not quiet:
        print(f"   🔒 Loading PII detection engine...")
    _ = get_analyzer()
    if not quiet:
        if sender_email:
            print(f"   📧 Filtering to sender: {sender_email}")
        print(f"   📅 Keeping emails from past {years} years")
        print(f"   ⏳ Processing...")

    for rec in iter_records(input_path):
        stats["total"] += 1

        if not quiet and stats["total"] % 500 == 0:
            print(f"      {stats['total']:,} scanned, {len(results):,} kept...")

        # Sender filter
        sender_raw = get_field(rec, "From", "from", "Sender", "sender", "emailFrom", "email_from")
        sender_addr = parseaddr(str(sender_raw or ""))[1].lower()
        if sender_email and sender_addr != sender_email.lower():
            stats["skipped_sender"] += 1
            continue

        # Date filter
        dt = None
        for k in ("Date", "date", "sent", "sentAt", "created_at", "createdAt"):
            v = get_field(rec, k)
            if v:
                dt = parse_date_any(v)
                if dt:
                    break
        if dt is None or dt < cutoff:
            stats["skipped_date"] += 1
            continue

        subj_raw = get_field(rec, "Subject", "subject") or ""
        body_raw = get_field(rec, "Body", "body", "Text", "text", "Content", "content") or ""
        to_raw = get_field(rec, "To", "to", "Recipient", "recipient") or ""

        # Auto-reply filter
        if is_auto_reply(rec, subj_raw, body_raw):
            stats["skipped_auto"] += 1
            continue

        # Clean and anonymize
        body_clean = cleanse_body(body_raw)
        subject_clean = cleanse_subject(subj_raw)
        to_clean = cleanse_to_field(to_raw)

        if not subject_clean and not body_clean:
            stats["skipped_empty"] += 1
            continue

        msg_id = get_field(rec, "Message-ID", "Message-Id", "MessageId", "message_id") or ""

        results.append({
            "Message-ID": msg_id.strip() if msg_id else None,
            "Sender": sender_addr,
            "To": to_clean,
            "Subject": subject_clean,
            "Body": body_clean
        })

    stats["kept"] = len(results)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    if not quiet:
        print(f"\n   {'─'*50}")
        print(f"   📊 CLEANING SUMMARY:")
        print(f"      Total scanned:    {stats['total']:,}")
        print(f"      ✓ Kept:           {stats['kept']:,}")
        if stats['skipped_sender'] > 0:
            print(f"      ✗ Wrong sender:   {stats['skipped_sender']:,}")
        if stats['skipped_date'] > 0:
            print(f"      ✗ Too old:        {stats['skipped_date']:,}")
        if stats['skipped_auto'] > 0:
            print(f"      ✗ Auto-replies:   {stats['skipped_auto']:,}")
        if stats['skipped_empty'] > 0:
            print(f"      ✗ Empty:          {stats['skipped_empty']:,}")
        print(f"   💾 Saved to: {os.path.basename(output_path)}")

    stats["output"] = output_path
    return stats


# =============================================================================
# STAGE 3: CURATION
# =============================================================================

BORING_KEYWORDS = [
    "invoice", "receipt", "password", "notification", "digest",
    "calendar", "invite", "zoom", "meeting rescheduled", "reminder",
    "unsubscribe", "terms and conditions", "login code",
    "reset your password", "security alert"
]

TOPIC_KEYWORDS = {
    "client": ["client", "proposal", "brief", "scope", "contract", "statement of work"],
    "strategy": ["strategy", "vision", "northstar", "long-term", "direction"],
    "update": ["status", "update", "weekly", "friday update", "checkpoint"],
    "feedback": ["feedback", "retro", "retrospective", "reflection", "debrief", "coaching"],
    "workshop": ["workshop", "session", "agenda", "facilitation"],
}


def label_topic(subject: str, body: str) -> str:
    text = ((subject or "") + " " + (body or "")).lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(w in text for w in keywords):
            return topic
    return "other"


def richness_score(body: str) -> int:
    if not body:
        return 0
    return len(body) + (body.count("\n\n") + body.count("\r\n\r\n")) * 200


def is_style_candidate(email: Dict[str, Any], min_chars: int = 200) -> bool:
    subject = email.get("Subject") or ""
    body = email.get("Body") or ""
    to_field = email.get("To") or ""

    if not subject or any(w in subject.lower() for w in BORING_KEYWORDS):
        return False
    if len(body.strip()) < min_chars:
        return False
    lower_to = to_field.lower()
    if "no-reply@" in lower_to or "noreply@" in lower_to or "notification" in lower_to:
        return False
    return True


def deduplicate_emails(
    candidates: List[Dict[str, Any]],
    threshold: float = 0.8,
    quiet: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Remove exact and near-duplicate emails, keeping the richest version.

    Uses two-level deduplication:
    1. Exact hash match (SHA-256 of normalized body)
    2. MinHash LSH for near-duplicates (Jaccard similarity)

    Args:
        candidates: List of email dicts with Body field
        threshold: Jaccard similarity threshold for near-duplicates (0.0-1.0)
        quiet: If True, suppress progress output

    Returns:
        Tuple of (deduplicated_list, stats_dict)
    """
    try:
        from datasketch import MinHash, MinHashLSH
        has_datasketch = True
    except ImportError:
        has_datasketch = False
        if not quiet:
            print("Warning: datasketch not installed, using exact-match only")

    # Sort by richness descending so we keep the best version first
    sorted_candidates = sorted(
        candidates,
        key=lambda e: richness_score(e.get("Body", "")),
        reverse=True
    )

    seen_hashes: Set[str] = set()
    kept: List[Dict[str, Any]] = []
    stats = {"exact_dupes": 0, "near_dupes": 0}

    # Initialize LSH if available
    lsh = None
    if has_datasketch:
        lsh = MinHashLSH(threshold=threshold, num_perm=128)

    for email in sorted_candidates:
        body = (email.get("Body") or "").strip().lower()
        body_normalized = re.sub(r'\s+', ' ', body)  # Normalize whitespace

        # Level 1: Exact hash match
        body_hash = hashlib.sha256(body_normalized.encode()).hexdigest()
        if body_hash in seen_hashes:
            stats["exact_dupes"] += 1
            continue
        seen_hashes.add(body_hash)

        # Level 2: MinHash LSH for near-duplicates
        if lsh is not None and len(body_normalized) > 50:
            mh = MinHash(num_perm=128)
            words = body_normalized.split()
            # Use 3-word shingles
            for i in range(max(1, len(words) - 2)):
                shingle = ' '.join(words[i:i+3])
                mh.update(shingle.encode('utf8'))

            # Check for near-duplicates
            if lsh.query(mh):
                stats["near_dupes"] += 1
                continue

            # Insert into LSH index
            email_id = email.get("Message-ID") or str(len(kept))
            lsh.insert(email_id, mh)

        kept.append(email)

    stats["kept"] = len(kept)
    stats["removed"] = len(candidates) - len(kept)

    if not quiet:
        print(f"      🗑️  Removed {stats['exact_dupes']:,} exact + {stats['near_dupes']:,} near-duplicates")

    return kept, stats


def build_shortlist(
    input_path: str,
    output_path: str = "style_shortlist.csv",
    per_topic: int = 200,
    min_chars: int = 200,
    dedupe: bool = True,
    dedupe_threshold: float = 0.8,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Build a curated shortlist of high-quality style samples.

    Args:
        input_path: Path to cleaned emails JSON
        output_path: Path to output CSV
        per_topic: Max emails per topic bucket
        min_chars: Minimum body length
        dedupe: If True, remove duplicate and near-duplicate emails
        dedupe_threshold: Jaccard similarity threshold for near-duplicates
        quiet: If True, suppress progress output

    Returns:
        Statistics dict
    """
    with open(input_path, "r", encoding="utf-8") as f:
        emails = json.load(f)

    if not quiet:
        print(f"   📂 Loaded {len(emails):,} cleaned emails")

    # Filter candidates
    candidates = [e for e in emails if is_style_candidate(e, min_chars)]
    filtered_out = len(emails) - len(candidates)
    if not quiet:
        print(f"   🔍 Quality filter: {len(candidates):,} candidates ({filtered_out:,} too short/boring)")

    # Deduplicate
    dedupe_stats = None
    if dedupe:
        if not quiet:
            print(f"   🧹 Removing duplicates...")
        candidates, dedupe_stats = deduplicate_emails(candidates, dedupe_threshold, quiet)
        if not quiet:
            print(f"      ✓ {len(candidates):,} unique emails remain")

    # Bucket by topic
    if not quiet:
        print(f"   🏷️  Categorizing by topic...")
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in candidates:
        topic = label_topic(e.get("Subject", ""), e.get("Body", ""))
        e["_topic"] = topic
        e["_richness"] = richness_score(e.get("Body", ""))
        buckets.setdefault(topic, []).append(e)

    # Select top N per topic
    shortlisted = []
    topic_stats = {}
    topic_emojis = {"client": "👔", "strategy": "🎯", "update": "📝", "feedback": "💬", "workshop": "🛠️", "other": "📋"}

    if not quiet:
        print(f"\n   📊 TOPIC BREAKDOWN:")
    for topic, items in sorted(buckets.items(), key=lambda x: len(x[1]), reverse=True):
        items_sorted = sorted(items, key=lambda x: x["_richness"], reverse=True)
        picked = items_sorted[:per_topic]
        topic_stats[topic] = {"total": len(items), "selected": len(picked)}
        emoji = topic_emojis.get(topic, "📋")
        if not quiet:
            print(f"      {emoji} {topic}: {len(picked):,} selected (from {len(items):,})")
        shortlisted.extend(picked)

    # Write CSV
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "message_id", "subject", "body", "to",
            "topic", "body_length", "paragraph_count", "richness_score"
        ])
        for idx, e in enumerate(shortlisted):
            body = e.get("Body") or ""
            writer.writerow([
                idx,
                e.get("Message-ID") or "",
                (e.get("Subject") or "").replace("\n", " "),
                body,
                e.get("To") or "",
                e.get("_topic"),
                len(body),
                body.count("\n\n"),
                e.get("_richness"),
            ])

    if not quiet:
        print(f"\n   {'─'*50}")
        print(f"   ✅ CURATION COMPLETE!")
        print(f"      {len(shortlisted):,} high-quality emails selected")
        print(f"   💾 Saved to: {os.path.basename(output_path)}")

    result = {
        "total_input": len(emails),
        "candidates": len(candidates),
        "shortlisted": len(shortlisted),
        "topics": topic_stats,
        "output": output_path
    }
    if dedupe_stats:
        result["deduplication"] = dedupe_stats
    return result


# =============================================================================
# FULL PIPELINE
# =============================================================================

def needs_mbox_import(input_path: str) -> bool:
    """Check if input needs MBOX import (vs already being JSON)."""
    lower = input_path.lower()
    # Direct mbox file
    if lower.endswith(".mbox"):
        return True
    # Zip file (Google Takeout)
    if lower.endswith(".zip"):
        return True
    # Directory (might contain mbox files)
    if os.path.isdir(input_path):
        return True
    # JSON files don't need import
    if lower.endswith(".json") or lower.endswith(".jsonl"):
        return False
    # Default: assume it needs import
    return True


def run_pipeline(
    input_path: str,
    sender_email: Optional[str] = None,
    output_dir: str = ".",
    per_topic: int = 200,
    quiet: bool = False,
    fresh: bool = False
) -> Dict[str, Any]:
    """
    Run the full pipeline: import (if mbox/zip/dir) -> convert -> clean -> curate.

    Supports graceful restart - skips stages if output files already exist.
    Use fresh=True to force re-running all stages.

    Args:
        input_path: Path to MBOX file, directory, zip file, or JSON file
        sender_email: Only keep emails from this sender
        output_dir: Directory for output files
        per_topic: Max emails per topic in shortlist
        quiet: If True, suppress progress output
        fresh: If True, ignore existing files and re-run everything

    Returns:
        Combined statistics from all stages
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    json_path = input_path

    # Define output paths
    raw_json_path = str(output_dir / "emails_raw.json")
    jsonl_path = str(output_dir / "emails.jsonl")
    cleaned_path = str(output_dir / "cleaned_emails.json")
    shortlist_path = str(output_dir / "style_shortlist.csv")

    # Stage 0: Import MBOX (if needed)
    if needs_mbox_import(input_path):
        json_path = raw_json_path

        if not fresh and os.path.exists(json_path):
            if not quiet:
                size_mb = os.path.getsize(json_path) / (1024 * 1024)
                print(f"\n⏭️  SKIPPING IMPORT (found existing emails_raw.json, {size_mb:.1f} MB)")
                print(f"   Use --fresh to re-import from source")
            # Load stats from existing file
            with open(json_path, "r") as f:
                data = json.load(f)
                count = len(data) if isinstance(data, list) else 1
            results["import"] = {"total": count, "imported": count, "skipped": 0, "output": json_path, "resumed": True}
        else:
            results["import"] = import_mbox(input_path, json_path, quiet=quiet)

            # Check if any emails were imported
            if results["import"]["imported"] == 0:
                if not quiet:
                    print("\n❌ Pipeline stopped: No emails to process")
                return results

    # Stage 1: Convert to JSONL
    if not fresh and os.path.exists(jsonl_path):
        if not quiet:
            size_mb = os.path.getsize(jsonl_path) / (1024 * 1024)
            print(f"\n⏭️  SKIPPING CONVERT (found existing emails.jsonl, {size_mb:.1f} MB)")
        with open(jsonl_path, "r") as f:
            count = sum(1 for _ in f)
        results["convert"] = {"total": count, "kept": count, "output": jsonl_path, "resumed": True}
    else:
        if not quiet:
            print(f"\n{'='*60}")
            print(f"🔄 STAGE 1: FORMAT CONVERSION")
            print(f"{'='*60}")
        results["convert"] = convert_to_jsonl(json_path, jsonl_path, quiet=quiet)

    # Stage 2: Clean & Anonymize
    if not fresh and os.path.exists(cleaned_path):
        if not quiet:
            size_mb = os.path.getsize(cleaned_path) / (1024 * 1024)
            print(f"\n⏭️  SKIPPING CLEAN (found existing cleaned_emails.json, {size_mb:.1f} MB)")
        with open(cleaned_path, "r") as f:
            data = json.load(f)
        results["clean"] = {"total": len(data), "kept": len(data), "output": cleaned_path, "resumed": True}
    else:
        if not quiet:
            print(f"\n{'='*60}")
            print(f"🔒 STAGE 2: CLEANING & PII ANONYMIZATION")
            print(f"{'='*60}")
        results["clean"] = clean_emails(jsonl_path, cleaned_path, sender_email, quiet=quiet)

        # Check if any emails passed cleaning
        if results["clean"]["kept"] == 0:
            if not quiet:
                print(f"\n❌ No emails passed cleaning filters!")
                print(f"   Check your --sender email address or date range.")
            return results

    # Stage 3: Curate Shortlist
    if not fresh and os.path.exists(shortlist_path):
        if not quiet:
            size_kb = os.path.getsize(shortlist_path) / 1024
            print(f"\n⏭️  SKIPPING CURATE (found existing style_shortlist.csv, {size_kb:.1f} KB)")
        with open(shortlist_path, "r") as f:
            count = sum(1 for _ in f) - 1  # minus header
        results["curate"] = {"total_input": results["clean"]["kept"], "shortlisted": count, "output": shortlist_path, "resumed": True}
    else:
        if not quiet:
            print(f"\n{'='*60}")
            print(f"⭐ STAGE 3: QUALITY CURATION")
            print(f"{'='*60}")
        results["curate"] = build_shortlist(cleaned_path, shortlist_path, per_topic, quiet=quiet)

    if not quiet:
        print(f"\n{'='*60}")
        print(f"🎉 PIPELINE COMPLETE!")
        print(f"{'='*60}")
        print(f"\n   📁 Output files in: {output_dir}/")
        print(f"      • emails_raw.json     - Raw imported emails")
        print(f"      • emails.jsonl        - Converted format")
        print(f"      • cleaned_emails.json - Anonymized emails")
        print(f"      • style_shortlist.csv - ⭐ Final curated samples")
        print(f"\n   📊 Final count: {results['curate']['shortlisted']:,} style samples ready!")
        print(f"\n   🚀 Next step: Use style_shortlist.csv for fine-tuning\n")

    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Voice Synthesizer - Email data preparation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
📦 GOOGLE TAKEOUT INSTRUCTIONS:
  1. Go to https://takeout.google.com
  2. Deselect all, then select only 'Mail'
  3. Click 'Next' → Choose 'Export once'
  4. File size: Select 50 GB (avoids splitting into multiple zips)
  5. Download when ready

📂 SUPPORTED INPUT FORMATS:
  • .zip file    → Extracts and finds all .mbox files
  • directory/   → Searches recursively for .mbox files
  • .mbox file   → Processes single file directly
  • .json file   → Skips import, starts at conversion stage

💡 EXAMPLES:
  # Full pipeline from Google Takeout zip
  python pipeline.py run takeout.zip --sender you@gmail.com

  # Full pipeline from extracted folder
  python pipeline.py run ./Takeout/ --sender you@gmail.com

  # Full pipeline from single MBOX
  python pipeline.py run "All mail.mbox" --sender you@gmail.com

  # Individual stages
  python pipeline.py import ./Takeout/ --out emails.json
  python pipeline.py clean emails.jsonl --sender you@gmail.com
  python pipeline.py curate cleaned_emails.json --per-topic 100
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run full pipeline
    run_parser = subparsers.add_parser("run", help="Run full pipeline")
    run_parser.add_argument("input", help="Input: .zip, directory, .mbox, or .json file")
    run_parser.add_argument("--sender", help="Filter to emails from this sender")
    run_parser.add_argument("--output-dir", default=".", help="Output directory")
    run_parser.add_argument("--per-topic", type=int, default=200, help="Max emails per topic")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed JSON output")
    run_parser.add_argument("--fresh", action="store_true", help="Ignore existing files and re-run all stages")

    # Import MBOX
    import_parser = subparsers.add_parser("import", help="Import MBOX/zip/directory to JSON")
    import_parser.add_argument("input", help="Input: .zip, directory, or .mbox file")
    import_parser.add_argument("--out", help="Output JSON file")
    import_parser.add_argument("--json-stats", action="store_true", help="Output JSON stats only")

    # Convert JSON to JSONL
    conv_parser = subparsers.add_parser("convert", help="Convert JSON to JSONL")
    conv_parser.add_argument("input", help="Input JSON file")
    conv_parser.add_argument("--out", help="Output JSONL file")
    conv_parser.add_argument("--no-filter", action="store_true", help="Don't filter fields")
    conv_parser.add_argument("--json-stats", action="store_true", help="Output JSON stats only")

    # Clean and anonymize
    clean_parser = subparsers.add_parser("clean", help="Clean and anonymize emails")
    clean_parser.add_argument("input", help="Input JSON/JSONL file")
    clean_parser.add_argument("--out", default="cleaned_emails.json", help="Output JSON file")
    clean_parser.add_argument("--sender", help="Filter to emails from this sender")
    clean_parser.add_argument("--years", type=int, default=5, help="Keep emails from past N years")
    clean_parser.add_argument("--json-stats", action="store_true", help="Output JSON stats only")

    # Curate shortlist
    curate_parser = subparsers.add_parser("curate", help="Build style shortlist")
    curate_parser.add_argument("input", help="Input cleaned JSON file")
    curate_parser.add_argument("--out", default="style_shortlist.csv", help="Output CSV file")
    curate_parser.add_argument("--per-topic", type=int, default=200, help="Max emails per topic")
    curate_parser.add_argument("--min-chars", type=int, default=200, help="Minimum body length")
    curate_parser.add_argument("--no-dedupe", action="store_true", help="Skip deduplication")
    curate_parser.add_argument("--dedupe-threshold", type=float, default=0.8,
                               help="Similarity threshold for near-duplicate detection (0.0-1.0)")
    curate_parser.add_argument("--json-stats", action="store_true", help="Output JSON stats only")

    detect_parser = subparsers.add_parser("detect-owner", help="Detect owner email from mbox")
    detect_parser.add_argument("input", help="Input MBOX file or directory")

    args = parser.parse_args()

    if args.command == "run":
        results = run_pipeline(args.input, args.sender, args.output_dir, args.per_topic, fresh=args.fresh)

        # Show summary table (unless pipeline failed early)
        if "curate" in results:
            print(f"\n{'─'*60}")
            print(f"📊 PIPELINE SUMMARY")
            print(f"{'─'*60}")
            print(f"{'Stage':<20} {'Input':>12} {'Output':>12} {'Filtered':>12}")
            print(f"{'─'*20} {'─'*12} {'─'*12} {'─'*12}")

            if "import" in results:
                imp = results["import"]
                print(f"{'Import':<20} {imp['total']:>12,} {imp['imported']:>12,} {imp['skipped']:>12,}")

            conv = results["convert"]
            print(f"{'Convert':<20} {conv['total']:>12,} {conv['kept']:>12,} {conv['total']-conv['kept']:>12,}")

            clean = results["clean"]
            print(f"{'Clean & Anonymize':<20} {clean['total']:>12,} {clean['kept']:>12,} {clean['total']-clean['kept']:>12,}")

            curate = results["curate"]
            print(f"{'Curate':<20} {curate['total_input']:>12,} {curate['shortlisted']:>12,} {curate['total_input']-curate['shortlisted']:>12,}")

            print(f"{'─'*60}")

        # Verbose: show full JSON
        if args.verbose:
            print(f"\n📋 VERBOSE OUTPUT:")
            print(json.dumps(results, indent=2, default=str))

    elif args.command == "import":
        results = import_mbox(args.input, args.out, quiet=getattr(args, 'json_stats', False))
        if getattr(args, 'json_stats', False):
            print(json.dumps(results))
        elif results['imported'] > 0:
            files_msg = f" from {results['files']} files" if results.get('files', 1) > 1 else ""
            print(f"\n✅ Done! Imported {results['imported']} of {results['total']} emails{files_msg}.")
            print(f"📄 Output: {results['output']}")

    elif args.command == "convert":
        results = convert_to_jsonl(args.input, args.out, not args.no_filter, quiet=getattr(args, 'json_stats', False))
        if getattr(args, 'json_stats', False):
            print(json.dumps(results))
        else:
            print(f"Done. Output: {results['output']}")

    elif args.command == "clean":
        results = clean_emails(args.input, args.out, args.sender, args.years, quiet=getattr(args, 'json_stats', False))
        if getattr(args, 'json_stats', False):
            print(json.dumps(results))
        else:
            print(f"\nDone. Kept {results['kept']} of {results['total']} emails.")
            print(f"Output: {results['output']}")

    elif args.command == "curate":
        results = build_shortlist(
            args.input, args.out, args.per_topic, args.min_chars,
            dedupe=not args.no_dedupe,
            dedupe_threshold=args.dedupe_threshold,
            quiet=getattr(args, 'json_stats', False)
        )
        if getattr(args, 'json_stats', False):
            print(json.dumps(results))
        else:
            print(f"\nDone. Shortlisted {results['shortlisted']} emails.")
            if "deduplication" in results:
                d = results["deduplication"]
                print(f"Removed {d['removed']} duplicates ({d['exact_dupes']} exact, {d['near_dupes']} near)")
            print(f"Output: {results['output']}")

    elif args.command == "detect-owner":
        email = detect_owner_email(args.input)
        if email:
            print(email)
        else:
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
