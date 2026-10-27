# REPORT — Enron Insight (Team Neural Nexus)

**1. Approach.** One offline pipeline streams the CMU archive (517,401 files), parses each message, removes quoted replies and disclaimers, deduplicates by content hash (254,361 unique emails) and stores everything in SQLite. Explainable rules flag an email only when the sender's own words ask to destroy records, keep something secret or avoid a written record; external/rare recipients and weekend sending only add points. A Streamlit dashboard shows volume over time, a who-emails-whom network, and a ranked list where every flag opens its highlighted sentence, score breakdown and original file.

**2. Tools.** Python 3.9, standard-library `email`/`tarfile`/`sqlite3`, pandas, NetworkX, Plotly, Streamlit, pytest. No ML model or LLM.

**3. Constraints.** 6.5-hour build, one laptop, slow venue Wi-Fi (no Python upgrade), no labelled data.

**4. Assumptions.** "Suspicious" = worth a compliance reviewer's time, not wrongdoing. Header timezones do not reflect senders' local time. 1998–2002 is the valid date window.

**5. Top design decisions.** (1) Content-hash dedup — Message-ID is unique per file. (2) Language required to flag; context only amplifies — context-only scoring flagged 12.5% of all email. (3) No hour-of-day rule — 28% of email falls in 22:00–05:59 by header. (4) Rules read authored text only and skip press/newsletter text. (5) Precompute into SQLite; the UI never re-parses.

**6. AI assistance.** Claude Code (Anthropic) drafted the parser, pipeline, scoring, app, tests and docs from our spec. We verified with 36 automated tests, by cross-checking counts against an independent profiling pass, and by reading real flagged sentences, which exposed false positives we then fixed. _Team: add who reviewed which module._

**7. Prior work.** CMU Enron corpus documentation; the Powers Report (2002) for entity names used as context; the team's implementation spec.

**8. Failed attempts.** Message-ID and raw-hash dedup (found no duplicates); off-hours rule (noise); context-only scoring (12.5% flagged); rules v1.0.0 ranked press digests and a survey invite at the top → v1.1.0 filters. Details: `docs/FAILED_ATTEMPTS.md`.

**Precision:** pending manual review of `docs/ANNOTATION_TEMPLATE.csv` (top 20 + 20 random, seed 42).
