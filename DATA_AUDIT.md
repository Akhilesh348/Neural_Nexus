# Data audit (measured on 27 Oct 2026)

All figures come from streaming passes over `enron_mail_20150507.tar.gz` (scripts in this repo and a
one-off profiling script). Nothing here is estimated unless marked.

## Input

- **No CSV was provided.** The input is the CMU maildir archive (the problem statement's primary
  source), 443,254,787 bytes. `src/pipeline.py` reads it directly; a Kaggle `file,email` CSV is also supported.
- Machine: Windows 11, 16 GB RAM, 12 logical CPUs, Python 3.9.5.

## Scale

| Measure | Value |
|---|---|
| Files (messages) | 517,401 |
| Mailboxes / folders | 150 / 1,940 |
| Uncompressed size | 1.42 GB; largest message 2.0 MB |
| Full profiling pass | 203 s |
| Non-UTF-8 files | 90 (decoded as latin-1) |
| Parse failures (our parser) | 0 |

## Structure

- RFC-822 text: headers, blank line, plain-text body. Content-Type is `text/plain` on 253,888 of the
  253,891 unique valid emails; no HTML parts. Transfer encodings: 7bit 243,916, quoted-printable 9,970, base64 2.
- Headers present on ~100%: Message-ID, Date, From, Subject, X-From, X-To, X-cc, X-bcc, X-Folder, X-Origin, X-FileName.
  `To` missing on 21,847 files (4.2%). `Cc`/`Bcc` on 127,881 — `Bcc` duplicates `Cc`.
- No `In-Reply-To` / `References` headers, so threads can only be approximated by subject.
- `From` is a bare address (82% @enron.com); `X-From` holds display names, often Exchange-style
  (`Fagan, Fran </O=ENRON/OU=NA/CN=...>`). Some addresses are malformed (e.g. `.alex@enron.com`).

## Data-quality findings that changed the design

| Finding | Evidence | Decision |
|---|---|---|
| Message-ID unique per file | 517,401 unique IDs | Cannot dedup on it |
| ~50% duplicate copies | content hash → 254,374 unique emails | Dedup by sender+Date+subject+body hash; keep all paths |
| Bogus dates | 522 in 1979, a few in 2004–2044; 483 unique emails outside 1998–2002 | Analysis window 1998–2002 |
| All Date headers -0700/-0800 | 269,085 PDT + 248,316 PST | Timezone is not the sender's |
| Header hours shifted | forwarded Lotus mails show in-body local time ~3 h before header time; hourly histogram peaks 01:00–09:00; 28.2% of unique emails fall in 22:00–05:59 | No hour-of-day rule |
| Quoted chains | 122,502 files contain "Original Message"/"Forwarded by"; spec phrases: 168 emails in authored text vs 1,012 incl. quoted | Rules read authored text only |
| Disclaimers | "confidential" in 26,717 files, "delete" in 19,211, mostly footers / folder names | Disclaimer window filter; "confidential" not a rule |
| Mass mailings | 15,792 files with 50+ recipients | Graph limited to top 15–50 addresses |
| Pure forwards | 19,104 unique emails have no authored text | Cannot be flagged (limitation) |

## Subset policy

The full corpus is processed (no subset). `--limit N` exists only for development runs and the app
shows a warning banner whenever a database was built with a limit.
