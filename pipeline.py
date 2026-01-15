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
import json
import mailbox
import os
import re
import sys
from datetime import datetime, timezone
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


def import_mbox(
    input_path: str,
    output_path: Optional[str] = None,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Import an MBOX file (e.g., from Google Takeout) to JSON.
    Strips attachments, keeps only text content.

    Args:
        input_path: Path to MBOX file
        output_path: Path to output JSON file (default: input with .json extension)
        quiet: If True, suppress progress output

    Returns:
        Statistics dict
    """
    if output_path is None:
        base = input_path.rsplit(".", 1)[0] if "." in input_path else input_path
        output_path = base + ".json"

    if not quiet:
        print(f"Opening MBOX file: {input_path}")

    mbox = mailbox.mbox(input_path)
    emails = []
    total = 0
    skipped = 0

    for message in mbox:
        total += 1

        if not quiet and total % 500 == 0:
            print(f"  Processed {total} messages...")

        try:
            # Extract headers
            msg_id = message.get("Message-ID", "")
            from_addr = message.get("From", "")
            to_addr = message.get("To", "")
            cc_addr = message.get("Cc", "")
            subject = message.get("Subject", "")
            date = message.get("Date", "")

            # Gmail-specific: get labels
            labels = message.get("X-Gmail-Labels", "")

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
                print(f"  Warning: Failed to parse message {total}: {e}")
            skipped += 1
            continue

    mbox.close()

    if not quiet:
        print(f"Writing {len(emails)} emails to {output_path}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)

    return {
        "total": total,
        "imported": len(emails),
        "skipped": skipped,
        "output": output_path
    }


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
            if not quiet and total % 1000 == 0:
                print(f"  Processed {total} records...")

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
        print("Loading Presidio analyzer...")
    _ = get_analyzer()
    if not quiet:
        print("Processing emails...")

    for rec in iter_records(input_path):
        stats["total"] += 1

        if not quiet and stats["total"] % 100 == 0:
            print(f"  Processed {stats['total']} emails...")

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


def build_shortlist(
    input_path: str,
    output_path: str = "style_shortlist.csv",
    per_topic: int = 200,
    min_chars: int = 200,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Build a curated shortlist of high-quality style samples.

    Args:
        input_path: Path to cleaned emails JSON
        output_path: Path to output CSV
        per_topic: Max emails per topic bucket
        min_chars: Minimum body length
        quiet: If True, suppress progress output

    Returns:
        Statistics dict
    """
    with open(input_path, "r", encoding="utf-8") as f:
        emails = json.load(f)

    if not quiet:
        print(f"Loaded {len(emails)} emails")

    # Filter candidates
    candidates = [e for e in emails if is_style_candidate(e, min_chars)]
    if not quiet:
        print(f"{len(candidates)} passed candidate filter")

    # Bucket by topic
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in candidates:
        topic = label_topic(e.get("Subject", ""), e.get("Body", ""))
        e["_topic"] = topic
        e["_richness"] = richness_score(e.get("Body", ""))
        buckets.setdefault(topic, []).append(e)

    # Select top N per topic
    shortlisted = []
    topic_stats = {}
    for topic, items in buckets.items():
        items_sorted = sorted(items, key=lambda x: x["_richness"], reverse=True)
        picked = items_sorted[:per_topic]
        topic_stats[topic] = {"total": len(items), "selected": len(picked)}
        if not quiet:
            print(f"  {topic}: {len(items)} candidates, keeping {len(picked)}")
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

    return {
        "total_input": len(emails),
        "candidates": len(candidates),
        "shortlisted": len(shortlisted),
        "topics": topic_stats,
        "output": output_path
    }


# =============================================================================
# FULL PIPELINE
# =============================================================================

def run_pipeline(
    input_path: str,
    sender_email: Optional[str] = None,
    output_dir: str = ".",
    per_topic: int = 200,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Run the full pipeline: import (if mbox) -> convert -> clean -> curate.

    Args:
        input_path: Path to MBOX file or JSON file
        sender_email: Only keep emails from this sender
        output_dir: Directory for output files
        per_topic: Max emails per topic in shortlist
        quiet: If True, suppress progress output

    Returns:
        Combined statistics from all stages
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    json_path = input_path

    # Stage 0: Import MBOX (if needed)
    if input_path.lower().endswith(".mbox"):
        if not quiet:
            print("\n=== Stage 0: Importing MBOX ===")
        json_path = str(output_dir / "emails_raw.json")
        results["import"] = import_mbox(input_path, json_path, quiet=quiet)

    # Stage 1: Convert to JSONL
    if not quiet:
        print("\n=== Stage 1: Converting to JSONL ===")
    jsonl_path = str(output_dir / "emails.jsonl")
    results["convert"] = convert_to_jsonl(json_path, jsonl_path, quiet=quiet)

    # Stage 2: Clean & Anonymize
    if not quiet:
        print("\n=== Stage 2: Cleaning & Anonymizing ===")
    cleaned_path = str(output_dir / "cleaned_emails.json")
    results["clean"] = clean_emails(jsonl_path, cleaned_path, sender_email, quiet=quiet)

    # Stage 3: Curate Shortlist
    if not quiet:
        print("\n=== Stage 3: Building Shortlist ===")
    shortlist_path = str(output_dir / "style_shortlist.csv")
    results["curate"] = build_shortlist(cleaned_path, shortlist_path, per_topic, quiet=quiet)

    if not quiet:
        print("\n=== Pipeline Complete ===")
        print(f"  Shortlist: {shortlist_path}")

    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Voice Synthesizer - Email data preparation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from MBOX (Google Takeout)
  python pipeline.py run "All mail.mbox" --sender user@example.com

  # Full pipeline from JSON
  python pipeline.py run emails.json --sender user@example.com

  # Individual stages
  python pipeline.py import "All mail.mbox" --out emails.json
  python pipeline.py convert emails.json --out emails.jsonl
  python pipeline.py clean emails.jsonl --sender user@example.com
  python pipeline.py curate cleaned_emails.json --per-topic 100
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run full pipeline
    run_parser = subparsers.add_parser("run", help="Run full pipeline (MBOX or JSON input)")
    run_parser.add_argument("input", help="Input MBOX or JSON file")
    run_parser.add_argument("--sender", help="Filter to emails from this sender")
    run_parser.add_argument("--output-dir", default=".", help="Output directory")
    run_parser.add_argument("--per-topic", type=int, default=200, help="Max emails per topic")

    # Import MBOX
    import_parser = subparsers.add_parser("import", help="Import MBOX file to JSON")
    import_parser.add_argument("input", help="Input MBOX file (from Google Takeout)")
    import_parser.add_argument("--out", help="Output JSON file")

    # Convert JSON to JSONL
    conv_parser = subparsers.add_parser("convert", help="Convert JSON to JSONL")
    conv_parser.add_argument("input", help="Input JSON file")
    conv_parser.add_argument("--out", help="Output JSONL file")
    conv_parser.add_argument("--no-filter", action="store_true", help="Don't filter fields")

    # Clean and anonymize
    clean_parser = subparsers.add_parser("clean", help="Clean and anonymize emails")
    clean_parser.add_argument("input", help="Input JSON/JSONL file")
    clean_parser.add_argument("--out", default="cleaned_emails.json", help="Output JSON file")
    clean_parser.add_argument("--sender", help="Filter to emails from this sender")
    clean_parser.add_argument("--years", type=int, default=5, help="Keep emails from past N years")

    # Curate shortlist
    curate_parser = subparsers.add_parser("curate", help="Build style shortlist")
    curate_parser.add_argument("input", help="Input cleaned JSON file")
    curate_parser.add_argument("--out", default="style_shortlist.csv", help="Output CSV file")
    curate_parser.add_argument("--per-topic", type=int, default=200, help="Max emails per topic")
    curate_parser.add_argument("--min-chars", type=int, default=200, help="Minimum body length")

    args = parser.parse_args()

    if args.command == "run":
        results = run_pipeline(args.input, args.sender, args.output_dir, args.per_topic)
        print(json.dumps(results, indent=2, default=str))

    elif args.command == "import":
        results = import_mbox(args.input, args.out)
        print(f"\nDone. Imported {results['imported']} of {results['total']} emails.")
        print(f"Output: {results['output']}")

    elif args.command == "convert":
        results = convert_to_jsonl(args.input, args.out, not args.no_filter)
        print(f"Done. Output: {results['output']}")

    elif args.command == "clean":
        results = clean_emails(args.input, args.out, args.sender, args.years)
        print(f"\nDone. Kept {results['kept']} of {results['total']} emails.")
        print(f"Output: {results['output']}")

    elif args.command == "curate":
        results = build_shortlist(args.input, args.out, args.per_topic, args.min_chars)
        print(f"\nDone. Shortlisted {results['shortlisted']} emails.")
        print(f"Output: {results['output']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
