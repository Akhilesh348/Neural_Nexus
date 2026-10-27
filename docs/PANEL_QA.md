# Panel Q&A and demo script

## 90-second demo

1. **(10 s) Overview** — "517,401 mailbox files, but only ~254k are unique emails — half are copies across folders. We parse, deduplicate, and keep every original path."
2. **(20 s) Volume chart** — "This answers: how does email volume change over time? Traffic climbs through 2001 and changes around the October 2001 disclosure." Hover a month.
3. **(30 s) Flagged emails** — "We rank emails for review. A flag needs explicit language — asking to destroy records, keep something secret, or avoid a written record. Context only adds points." Select the top row: show K/C/T breakdown, the highlighted sentence, the raw email and its source files.
4. **(15 s) Network & people** — "Who communicates most with whom? Thickness is email count. Selecting a person shows their flagged emails and evidence — centrality alone never flags anyone."
5. **(15 s) Method** — "Rules and weights are in one config file with a version. Precision is measured by two team members on the top 20 plus 20 random flags; it is computed only from those human labels."

## Likely questions

**Why this architecture?** Parsing 517k files takes minutes, so it runs once offline into SQLite; the app only queries precomputed tables and loads in seconds. Each stage (parse, score, graph, UI) is a separate module with its own tests.

**Why Python?** Standard-library `email` and `tarfile` handle the raw corpus; pandas, NetworkX, Plotly and Streamlit cover analysis and UI in one language the whole team knows.

**Why Streamlit instead of React?** One codebase, built-in caching and row selection, a working UI in minutes. React + API would double the code for no gain in a single-machine demo. Trade-off: less layout control.

**Why SQLite instead of only pandas?** One portable file, indexed lookups for the evidence view, SQL aggregates for graph and people tables. pandas is still used for scoring and charts. Scaling path: PostgreSQL or DuckDB.

**Why rules instead of machine learning?** There are no labels for "review-worthy", so a supervised model would be trained on nothing; unsupervised outliers are not the same as review-worthy and are hard to explain. Rules give the exact sentence as evidence and are reproducible. The problem statement says the simplest design meeting R1 and R2 scores highest.

**Why no LLM?** Optional per the brief; adds cost, latency, non-determinism and a prompt-injection surface (email bodies are untrusted text).

**How is the score calculated?** `min(100, K + C + T)`, only when a language rule fired. K: each rule counts its strongest phrase — strong 40 (destroy records, off the books, avoid a written record), medium 25 (keep this quiet, between you and me, off the record), weak 15 (don't forward this, delete this email) — cap 60, plus 10 for a finance-risk topic (LJM, SEC, Andersen, mark-to-market…). C: +10 external recipient, +10 rare pair, +10 sent to 1–3 people (cap 30). T: +5 weekend, +5 sent at an hour this sender rarely uses (cap 10). Low < 35 ≤ medium < 60 ≤ high.

**Why only 114 of 254k emails?** Measured funnel: 1,008 emails contain any of our phrases at all; 704 of those are disclaimers, IT notices, negations or idioms; 190 are press articles or bulk senders → 114 flagged. Real misconduct language is rare, and the job is triage — "here are the conversations to read first". We tested more phrases on the corpus and added only those that were mostly genuine ("keep this confidential", "don't discuss this with anyone", "prefer not to put this in writing").

**Why no date-window bonus?** We tried +10 for the investigation period (Oct 2001–Jan 2002) and removed it: it rewards *when* an email was sent rather than what it says, and would bias the ranking towards one period.

**Why phrase strengths?** In v1.1 every phrase was worth 30, so 72 of 110 flags tied and "please don't forward this" ranked equal to "take this risk off the books". Strengths reflect how specific the request is; they gave 11 distinct score levels instead of 5.
**How do you handle off-hours when header times are shifted?** A fixed window (22:00–06:00) would be noise: 28% of emails fall there by header time, and headers run ~3 h from the in-body local timestamps. So we compare each email with **the sender's own hourly pattern**: +5 if 5% or less of that sender's emails were sent within ±1 h of this hour (needs ≥ 50 dated emails, else "not evaluated"). A constant shift moves all of a sender's emails equally, so it cancels out — a unit test checks this. On the corpus it fires on 6 of 114 flagged emails, e.g. a sender with 5,518 emails who sends only 1.1% at that hour.

**How did you deduplicate?** Message-ID is unique per file in this corpus, so we hash sender + Date + subject + body. 517,401 files → ~254k unique emails; every original path is kept in `source_occurrences`.

**How do you validate?** Unit tests for parsing, scoring, evaluation and an end-to-end pipeline smoke test; manual inspection of sample flags (which led to rule fixes, see FAILED_ATTEMPTS); precision@20 from two independent human reviewers using a written rubric.

**False positives?** Legal disclaimers, IT notices, news articles quoted without a reply marker, negations. Disclaimer and negation filters address the first three partly; the rest are visible in the evidence view.

**How would it scale?** Shard ingest by mailbox, move to PostgreSQL/DuckDB, run rules per partition; the UI already reads only aggregates.

**How was AI used, and how did you verify it?** See REPORT.md: an AI coding assistant (Claude Code) drafted code and docs; we verified with automated tests, by checking counts against an independent profiling pass, and by reading real flagged sentences, which exposed false positives we then fixed.
