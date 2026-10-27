# Neural_Nexus — Enron Insight

**HCLTech AI Hackathon 2026, IIT Gandhinagar — Use Case 1: Enron Communications.**
Turns the raw Enron mailbox dump into a navigable dataset and a ranked, explainable list of emails
**flagged for review**, each linked to the exact sentence and original file that produced the flag.

> Outputs are "flagged for review" — never accusations. A score is a review priority, not a probability of wrongdoing. The corpus contains real people.

## 👥 Team Members

| S. No. | Name |
|---:|---|
| 1 | Vadithe Venkat Akhilesh Naik|
| 2 | Kovid Parmar|
| 3 | Praveen Kumar|
| 4 | Chinthala Shivamani |

### Contributions (three sentences each — to be completed by each member)

- **Vadithe Venkat Akhilesh Naik:** _TODO by member._
- **Kovid Parmar:** _TODO by member._
- **Praveen Kumar:** _TODO by member._
- **Chinthala Shivamani:** _TODO by member._

## Run steps (Windows / PowerShell, Python 3.9)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# put enron_mail_20150507.tar.gz (see source register) in the repo root
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m src.pipeline --input enron_mail_20150507.tar.gz          # full corpus, ~8 min
.\.venv\Scripts\python.exe -m streamlit run app.py                                     # http://localhost:8501
```

- Quick dev run: `python -m src.pipeline --input enron_mail_20150507.tar.gz --limit 20000 --db outputs/sample.db`, then `$env:ENRON_DB="outputs/sample.db"` before `streamlit run app.py`.
- A Kaggle-style CSV (`file,email` columns) also works: `--input emails.csv`.
- Precision workflow: `python -m src.evaluate template` → two reviewers fill `review_label` (yes/no/ambiguous) in copies of `docs/ANNOTATION_TEMPLATE.csv` → `python -m src.evaluate score --labels <fileA> <fileB>` → shown in the app.
- Note: the repo lives in a OneDrive folder; if SQLite reports "database is locked", pause OneDrive sync or set `--db`/`ENRON_DB` to a path outside OneDrive.

## What it does

| Requirement | Where |
|---|---|
| R1 visualization | **Overview** tab: "How does email volume change over time?" (monthly volume, event markers) and top senders; **Network & people** tab: "Who communicates most frequently with whom?" |
| R2 ranked, explainable flags | **Flagged emails** tab: ranked list → select → score breakdown (K/C/T), triggered rules with explanations, highlighted sentence, full original message, all source files. **Network & people**: people ranked by flagged emails → their evidence |
| Precision on a hand-checked sample | `src/evaluate.py` + **Method & precision** tab (computed only from human labels) |

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Data facts: [DATA_AUDIT.md](DATA_AUDIT.md) · Failed attempts: [docs/FAILED_ATTEMPTS.md](docs/FAILED_ATTEMPTS.md) · Panel prep: [docs/PANEL_QA.md](docs/PANEL_QA.md) · Report: [REPORT.md](REPORT.md)

```
src/parse.py      raw message → structured record (QP decode, authored vs quoted, boilerplate removal, content-hash id)
src/pipeline.py   tarball/CSV → SQLite (emails, recipients, source_occurrences) → scores → edges → people
src/scoring.py    explainable rules from config/rules.json → score, reasons, evidence, "not evaluated" notes
src/db.py         schema, indexes, evidence query
src/evaluate.py   annotation sheet + precision from human labels
app.py            Streamlit dashboard (reads SQLite only)
tests/            parser, scoring, evaluation, end-to-end pipeline smoke test
```

## Source register

| File | Source | URL | Downloaded | Notes |
|---|---|---|---|---|
| `enron_mail_20150507.tar.gz` (443,254,787 bytes, SHA-256 `B3DA1B3FE0369EC3140BB4FBCE94702C33B7DA810EC15D718B3FADF5CD748CA7`) | CMU Enron Email Dataset (primary source) | https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz | 2026-10-27 | Full corpus used; not committed (size) |
| `UseCase1_Enron_Communications 1.docx` | HCLTech (organizers) | provided at venue | 2026-10-27 | Problem statement; not committed |
| Publicly known event dates on the timeline (16 Oct 2001 Q3 loss disclosure, 2 Dec 2001 bankruptcy filing) and SPE names in rule K-TOPIC (LJM, Raptor, Chewco, JEDI, Whitewing) | Report of Investigation by the Special Investigative Committee of the Board of Directors of Enron Corp. ("Powers Report", 1 Feb 2002) — prior work, cited from general knowledge, not downloaded | public record | — | Used as context only |

## Failed attempts (summary — details in docs/FAILED_ATTEMPTS.md)

- Message-ID dedup and raw-text-hash dedup: both find no duplicates in this corpus → content hash.
- Off-hours rule: 28% of email falls in 22:00–05:59 by header and header times are shifted → not evaluated.
- Context-only scoring (external/rare/time): flagged 12.5% of all emails with no suspicious language → language now required.
- First rule set on a 20k sample: disclaimers, news usage of "shred", negations → filters added (24 → 8 sample flags).
- Rules v1.0.0 on the full corpus ranked press digests and a survey invitation at the top → v1.1.0 press/newsletter suppression and survey/negation fixes (360 → 110 flags; 185 suppressed, shown as "not evaluated").
- Rules v1.1.0 gave every phrase 30 points → only 5 distinct scores, spam and IT notices still flagged → v1.2.0 phrase strengths (strong 40 / medium 25 / weak 15), narrow-audience and investigation-period amplifiers, bulk-sender suppression. A v1.2 draft treating "off-balance-sheet" as a strong phrase flooded the top with routine finance memos; it was moved to context-only.

## Current results (full corpus, rules v1.2.0)

517,401 files · 0 parse failures · 254,361 unique emails (263,040 duplicate copies) · 253,879 dated 1998–2002 ·
**87 flagged for review** (11 high, 52 medium, 24 low; 11 distinct score levels) · 189 language hits set aside as
press/newsletter/bulk-sender text ("not evaluated") · 360,243 sender→recipient pairs · 64 people with flagged emails ·
pipeline 425 s, rescore ~2 min. **Precision: pending manual review.**

## Limitations

- Rules only see what is written; intent is not proven. Forwarded news/newsletters without a reply marker can still trigger rules.
- Header dates are converted to US/Pacific and do not reflect the sender's local time.
- Pure forwards (no comment by the sender) have no authored text and cannot be flagged.
- Precision is reported only after manual review; see the Method & precision tab.
