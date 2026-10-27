"""Analyse one new email with the same parser, rules and corpus statistics as the pipeline.

Used by the app's "Check a new email" tab and by `python -m src.check_email`.
The new email is not added to the database; corpus statistics (how often this sender
writes, to whom, and at which hours) come from the processed corpus.
"""
import pandas as pd

from src.parse import parse_message
from src.scoring import score_email


def build_raw(sender, to, subject, body, cc="", date=""):
    """Turn form fields into an RFC-822 message so it goes through the normal parser."""
    lines = [f"From: {sender.strip()}", f"To: {to.strip()}"]
    if cc.strip():
        lines.append(f"Cc: {cc.strip()}")
    if date.strip():
        lines.append(f"Date: {date.strip()}")
    lines.append(f"Subject: {subject.strip()}")
    return "\n".join(lines) + "\n\n" + body


def corpus_context(con, sender, recipients):
    """Sender volume, sender->recipient counts and the sender's hourly profile from the corpus."""
    n = con.execute("SELECT COUNT(*) FROM emails WHERE sender = ? AND date_valid = 1", (sender,)).fetchone()[0]
    pairs = {}
    for r in recipients:
        row = con.execute("SELECT n_emails FROM edges WHERE sender = ? AND recipient = ?", (sender, r)).fetchone()
        pairs[(sender, r)] = row[0] if row else 0
    hours = [0] * 24
    for h, c in con.execute("SELECT CAST(substr(sent_at_utc, 12, 2) AS INTEGER), COUNT(*) FROM emails "
                            "WHERE sender = ? AND date_valid = 1 GROUP BY 1", (sender,)):
        hours[h] = c
    return {sender: n}, pairs, {sender: hours}


def analyze_raw(raw, con, rules):
    """Parse and score a raw email. Returns (parsed record, ScoreResult)."""
    rec = parse_message(raw, "maildir/new-email/input/1.")
    d = rec["date_utc"]
    weekday = pd.Timestamp(d).tz_convert("US/Pacific").weekday() if rec["date_valid"] else None
    hour = d.hour if rec["date_valid"] else None
    sender_counts, pair_counts, sender_hours = corpus_context(con, rec["sender"], rec["recipients"])
    res = score_email(rec["subject"], rec["body_authored"], rec["sender"], rec["recipients"], weekday, rules,
                      pair_counts, sender_counts, d.isoformat() if d else None, hour, sender_hours)
    return rec, res
