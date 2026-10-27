# Failed attempts and changes of direction

Recorded as they happened on 27 Oct 2026. Numbers are measured on the real corpus.

| # | What we tried / planned | What happened | What we did instead |
|---|---|---|---|
| 1 | Deduplicate by `Message-ID` | All 517,401 files have a unique Message-ID, yet only ~254k distinct emails exist (same email in `all_documents`, `sent`, `discussion_threads`, …) | Content hash of sender + Date + subject + body |
| 2 | Spec: dedup by SHA-256 of the raw message | Raw text includes per-copy headers (Message-ID, X-Folder, X-FileName) → would find 0 of 262,468 duplicate copies | Same content hash as #1 |
| 3 | Off-hours rule (spec T: header hour 22:00–05:59) | 28.2% of all unique emails fall in that window; header times run ~3 h from in-body Lotus Notes timestamps; all headers are -0700/-0800 | Hour rule marked "not evaluated"; only a weekend amplifier kept |
| 4 | Spec C: +20 external recipient, +20 rare pair, added independently of language | 31,718 emails (12.5%) reached "medium" with no suspicious language; 10,840 outranked an email with one strong phrase | Language rule required to flag; C/T only add points |
| 5 | Scanning the whole body for phrases | Spec phrases hit 168 emails in authored text vs 1,012 including quoted replies (same thread re-flagged) | Split authored vs quoted text; rules read authored text only |
| 6 | Parser read bodies as-is | 9,970 emails are quoted-printable; soft line breaks can split phrases | Decode quoted-printable before splitting |
| 7 | Rules v0 on 20k-file sample: bare `shred`, disclaimer check on one line | 24 flags, many false: law-firm disclaimers wrapped over lines, news ("praised and shredded them", "shreds metal"), negation ("don't delete any e-mails") | Disclaimer check over a 250-char window, `shred/destroy` require a records object, negation check → 8 flags on the same sample |
| 9 | Rules v1.0.0 on the full corpus | 360 flags; 10 of the top 20 were press digests about the Andersen shredding (many rules fire on one long article); 12 of the top 20 after a first fix were copies of one survey invitation ("do not forward this link"); "should not delete any e-mails" passed the negation check | v1.1.0: press/newsletter suppression (N-NEWS, recorded as "not evaluated"), "this link"/"survey" exclusions, plain "not" as negation → 110 flags, 185 suppressed |
| 8 | First parse output to Parquet (`src/ingest.py`) | Worked (254,374 unique emails, 2.3 s load) but the team adopted the SQLite spec | Replaced by `src/pipeline.py` writing SQLite |

Known remaining false-positive sources: forwarded newsletters/news articles without a quote marker
(e.g. "off the record", "off the books" in press coverage), and survey/IT notices.
