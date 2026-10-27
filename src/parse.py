"""Parse one raw Enron message into a structured record.

Pure functions only (no I/O) so they can be unit tested. Email content is
treated strictly as data.
"""
import hashlib
import quopri
import re
from datetime import timezone
from email.parser import HeaderParser
from email.utils import getaddresses, parsedate_to_datetime

_HEADER_PARSER = HeaderParser()

# Analysis window: the corpus contains bogus dates (1979, 2043, ...).
VALID_YEARS = range(1998, 2003)

# Markers where the sender's own text ends and quoted/forwarded text begins.
# Derived from real messages in the corpus (Outlook, Lotus Notes, '>' quoting).
_QUOTE_MARKERS = re.compile(
    r"|".join([
        r"^[ \t]*-{2,}[ \t]*Original (?:Message|Appointment)[ \t]*-{2,}",
        r"^[ \t]*-{2,}[ \t]*Forwarded by",
        r"^[ \t]*From:[ \t].*\n[ \t]*Sent:",                                # Outlook header block
        r"^[ \t]*From:[ \t].* on \d{1,2}/\d{1,2}/\d{2,4}",                  # Lotus "From: X on 08/27/2001"
        r"^[^\n]*[@\"][^\n]* on \d{1,2}/\d{1,2}/\d{2,4} \d{1,2}:\d{2}(?::\d{2})? ?[AP]M[ \t]*$",  # '"X" <a@b> on 08/23/2001 12:46 PM'
        r"^[^\n]*\n[ \t]*\d{1,2}/\d{1,2}/\d{2,4} \d{1,2}:\d{2} ?[AP]M[ \t]*\n[ \t]*To:",  # Lotus name/date/To
        r"^[ \t]*>",                                                        # '>' quoted lines
        r"^\|-{3,}\+",                                                      # Lotus ASCII header table
    ]),
    re.MULTILINE | re.IGNORECASE,
)

# Legal/IT boilerplate removed from authored text so it never triggers rules.
_BOILERPLATE = re.compile(
    r"\*{5,}\s*This e-?mail is the property of Enron.*?(?:\*{5,}|$)"
    r"|This (?:e-?mail|message)[^.]{0,200}?intended (?:only )?(?:solely )?for the (?:use of the )?(?:individual|addressee|intended recipient).*?(?:\n\s*\n|$)"
    r"|If you are not the intended recipient.*?(?:\n\s*\n|$)",
    re.IGNORECASE | re.DOTALL,
)

_SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _addresses(*values):
    """Return de-duplicated, lower-cased addresses in first-seen order."""
    seen = []
    for _, addr in getaddresses([v for v in values if v]):
        addr = addr.strip().strip("<>'\"").lower()
        if addr and addr not in seen:
            seen.append(addr)
    return seen


def _display_name(x_from, fallback):
    """'Fagan, Fran </O=ENRON/...>' -> 'Fagan, Fran'."""
    name = (x_from or "").split("<")[0].strip().strip('"')
    return name or fallback


def decode_body(body, transfer_encoding):
    """Undo quoted-printable encoding (soft line breaks, =20, ...) so phrases are not split."""
    if (transfer_encoding or "").strip().lower() != "quoted-printable":
        return body
    data = quopri.decodestring(body.encode("utf-8", "replace"))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def split_body(body):
    """Split a body into (authored, quoted) at the first quote/forward marker."""
    m = _QUOTE_MARKERS.search(body)
    if not m:
        return body.strip(), ""
    return body[: m.start()].strip(), body[m.start():].strip()


def strip_boilerplate(text):
    return _BOILERPLATE.sub(" ", text).strip()


def normalize_subject(subject):
    return _SUBJECT_PREFIX.sub("", subject or "").strip().lower()


def make_email_id(sender, date_raw, subject, body):
    """Stable content id: the same email copied into several folders gets one id.

    Message-ID / X-Folder cannot be used: they differ for every copy in this corpus,
    so a hash of the raw file would find no duplicates at all.
    """
    key = "\x1f".join([sender, (date_raw or "").strip(), (subject or "").strip(),
                       _WS.sub(" ", body).strip()])
    return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:16]


def decode(raw_bytes):
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1")


def parse_message(raw, path):
    """Parse raw RFC-822 text from maildir `path` into a flat dict.

    Never raises on bad content: missing fields become empty values, an
    unparseable date becomes None and `parse_status` records what was missing.
    """
    raw = raw.replace("\r\n", "\n")
    head, _, body = raw.partition("\n\n")
    h = _HEADER_PARSER.parsestr(head + "\n")
    issues = []

    date_raw = h.get("Date", "") or ""
    try:
        date_utc = parsedate_to_datetime(date_raw).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        date_utc = None
        issues.append("bad_date")

    sender_list = _addresses(h.get("From", ""))
    sender = sender_list[0] if sender_list else ""
    if not sender:
        issues.append("no_sender")

    # recipient -> type (first seen wins). In this corpus Bcc duplicates Cc.
    rtypes = {}
    for rtype in ("to", "cc", "bcc"):
        for addr in _addresses(h.get(rtype.capitalize(), "")):
            rtypes.setdefault(addr, rtype)
    if not rtypes:
        issues.append("no_recipients")

    body = decode_body(body, h.get("Content-Transfer-Encoding"))
    subject = (h.get("Subject", "") or "").strip()
    authored, quoted = split_body(body)

    parts = path.split("/")
    mailbox = parts[1] if len(parts) > 2 else ""
    folder = "/".join(parts[2:-1]).lower() if len(parts) > 3 else ""

    return {
        "email_id": make_email_id(sender, date_raw, subject, body),
        "message_id": (h.get("Message-ID", "") or "").strip(),
        "date_utc": date_utc,
        "date_raw": date_raw,
        "date_valid": bool(date_utc and date_utc.year in VALID_YEARS),
        "sender": sender,
        "sender_name": _display_name(h.get("X-From"), sender),
        "recipient_types": rtypes,
        "recipients": list(rtypes),
        "n_recipients": len(rtypes),
        "subject": subject,
        "subject_norm": normalize_subject(subject),
        "body_authored": strip_boilerplate(authored),
        "body_quoted": quoted,
        "mailbox": mailbox,
        "folder": folder,
        "path": path,
        "raw_email": raw,
        "parse_status": "ok" if not issues else ",".join(issues),
    }
