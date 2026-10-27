# Architecture — Enron Insight

Goal: go from a raw mailbox dump to "here are the emails and people to review first",
with every flag traceable to the exact sentence and original file that produced it.

Based on the team's implementation spec (SQLite, `config/rules.json`, pipeline CLI), adapted to
what the real data showed (see `DATA_AUDIT.md` and `docs/FAILED_ATTEMPTS.md`).

## Data flow

```
enron_mail_20150507.tar.gz (CMU, 517,401 files)  — or a Kaggle file,email CSV
      │  streamed (tarfile / pandas chunks) — never extracted
      ▼
src/parse.py      raw text → record
                  headers: sender, To/Cc (Bcc merged, first type wins), UTC date, date_valid (1998–2002)
                  body: quoted-printable decoded → split authored | quoted → boilerplate removed
                  email_id = sha1(sender | Date | subject | body)  (content hash; Message-ID is per-file)
      ▼
src/pipeline.py   ingest  → SQLite: emails, recipients, source_occurrences   (batched, parameterized)
                  score   → risk_results   (src/scoring.py + config/rules.json)
                  graph   → edges          (sender→recipient counts, duplicates counted once)
                  people  → people         (sent, flagged, rate, max score)
                  meta    → counts, rule_version, runtime
      ▼
outputs/enron.db  (single file, read-only for the app)
      ▼
app.py (Streamlit + Plotly + NetworkX)  — never re-parses the corpus
  📊 Overview       R1: "How does email volume change over time?" + top senders
  🚩 Flagged emails R2: ranked list → select → score breakdown, rules, highlighted sentence, raw email, source files
  🕸️ Network/people R1: "Who communicates most frequently with whom?" + top pairs + people ranking → evidence
  📐 Method         rules, weights, rule frequency, precision (from human labels only)
      ▼
src/evaluate.py   annotation sheet (top 20 + 20 seeded random) → human labels → outputs/metrics.json
```

## Storage (SQLite, `src/db.py`)

| Table | Key | Purpose |
|---|---|---|
| `emails` | email_id | one row per unique email; raw text kept for evidence |
| `recipients` | (email_id, recipient) | to/cc/bcc type, deduplicated per email |
| `source_occurrences` | — | every maildir path a unique email was found at (traceability) |
| `risk_results` | email_id | score, priority, K/C/T points, rules, reasons_json, not_evaluated_json, rule_version |
| `edges` | (sender, recipient) | communication counts for the graph |
| `people` | sender | per-sender activity and flag statistics |
| `meta` | key | input, limit, counts, rule_version, build time |

## Scoring (`src/scoring.py`, `config/rules.json`)

`score = min(100, K + C + T)` — computed **only when a language rule fires** (K required). Rules v1.4.0.

| Signal | Rules | Points |
|---|---|---|
| K language (0–60) — flags the email | K-DESTROY (strong 40: shred/destroy/purge/get rid of records · weak 15: "delete this email"), K-OFF-BOOKS (strong 40), K-NO-RECORD (strong 40), K-SECRECY (medium 25: "keep this quiet / confidential", "between you and me", "off the record", "don't discuss this with anyone" · weak 15: "don't forward this", "eyes only"); K-NO-RECORD also covers "prefer not to put this in writing" (strong) and "rather discuss in person" (weak). Each rule counts its strongest phrase. | 15 / 25 / 40 per rule, cap 60 |
| K-TOPIC — adds only | finance-risk/investigation terms: LJM, Raptor, Chewco, JEDI, SPE, mark-to-market, prepay, Andersen, SEC, subpoena, restatement, off-balance-sheet, document retention/destruction, shredding, cover-up, cooking the books | +10 |
| C communication (0–30) — adds only | C-EXTERNAL (+10), C-RARE-PAIR (+10), C-NARROW 1–3 recipients (+10) | cap 30 |
| T timing (0–10) — adds only | T-WEEKEND (+5); T-OFF-HOURS (+5): sent at an hour when ≤ 5% of this sender's emails (±1 h) are sent; needs ≥ 50 dated emails from the sender, else "not evaluated". Sender-relative, so the corpus-wide header-time shift cancels out. No date-window bonus (team decision). | cap 10 |

Priority: low < 35 ≤ medium < 60 ≤ high (a lone weak phrase is honestly "low").

Rules read the subject + authored text only. A match is discarded if a disclaimer/IT/survey/idiom
term appears within 250 characters ("intended recipient", "workspace", "shred of", "rolled off the books" …),
and K-DESTROY is discarded when negated ("don't delete"). Two suppressions record the hit as
"not evaluated" instead of flagging: N-NEWS (press article/newsletter/ad markers) and N-BULK
(mailing-list or automated sender). After editing `config/rules.json`:
`python -m src.pipeline --rescore-only` (~2 min, no re-ingest). Missing data is "not evaluated", never zero risk.

## Key design decisions

1. **Offline pipeline, thin app** — parsing 517k files takes minutes; the demo loads instantly.
2. **Content-hash dedup** — Message-ID and folder headers differ per copy; hashing raw text finds no duplicates.
3. **Authored text only + disclaimer/negation filters** — quoted chains inflated phrase hits ~6×.
4. **Language required; context only amplifies** — context-only scoring flagged 12.5% of all email.
5. **No hour-of-day rule** — 28% of emails fall in 22:00–05:59 by header; header time ≠ local time.
6. **SQLite** — one portable file, indexed evidence lookups, SQL aggregates for graph/people.
7. **Streamlit** — one Python codebase, built-in caching and row selection.

## Scaling path

Ingest is one streaming pass → shard per mailbox and run in parallel; SQLite → PostgreSQL/DuckDB;
rules are pure functions → run per partition; the app reads only pre-aggregated tables.
