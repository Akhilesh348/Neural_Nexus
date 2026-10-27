"""End-to-end offline pipeline: source -> parse -> SQLite -> scores -> graph -> people.

Usage:
    python -m src.pipeline --input enron_mail_20150507.tar.gz            # full corpus
    python -m src.pipeline --input emails.csv                            # Kaggle file,email CSV
    python -m src.pipeline --input enron_mail_20150507.tar.gz --limit 20000 --db outputs/sample.db

--limit stops after N source files (dev runs). The full CMU corpus takes ~5-10 min.
"""
import argparse
import os
import tarfile
import time
from collections import Counter

import pandas as pd

from src import db
from src.parse import decode, parse_message
from src.scoring import Rules, score_email

BATCH = 5000


def iter_source(path, limit=None, chunksize=2000):
    """Yield (source_path, raw_text) from the CMU tarball or a Kaggle-style file,email CSV."""
    n = 0
    if path.lower().endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(path, "r:*") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                yield m.name, decode(tf.extractfile(m).read())
                n += 1
                if limit and n >= limit:
                    return
    elif path.lower().endswith(".csv"):
        for chunk in pd.read_csv(path, usecols=["file", "email"], chunksize=chunksize, dtype=str):
            for f, raw in zip(chunk["file"].fillna(""), chunk["email"].fillna("")):
                yield (f if f.startswith("maildir/") else "maildir/" + f), raw
                n += 1
                if limit and n >= limit:
                    return
    else:
        raise ValueError(f"Unsupported input (expected .tar.gz or .csv): {path}")


def _weekday_pacific(dt):
    return pd.Timestamp(dt).tz_convert("US/Pacific").weekday()


def ingest(con, path, limit=None):
    t0 = time.time()
    seen = {}
    email_rows, recip_rows, src_rows = [], [], []
    n_files = n_failed = 0

    def flush():
        con.executemany("INSERT INTO emails VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", email_rows)
        con.executemany("INSERT OR IGNORE INTO recipients VALUES (?,?,?)", recip_rows)
        con.executemany("INSERT INTO source_occurrences VALUES (?,?,?,?)", src_rows)
        con.commit()
        email_rows.clear(); recip_rows.clear(); src_rows.clear()

    for spath, raw in iter_source(path, limit):
        n_files += 1
        try:
            r = parse_message(raw, spath)
        except Exception as exc:  # one bad file must not stop the run
            n_failed += 1
            print(f"WARN parse failed {spath}: {exc}")
            continue
        eid = r["email_id"]
        src_rows.append((eid, spath, r["mailbox"], r["folder"]))
        if eid in seen:
            seen[eid] += 1
        else:
            seen[eid] = 1
            d = r["date_utc"]
            email_rows.append((
                eid, spath, r["message_id"], r["sender"], r["sender_name"],
                d.isoformat() if d else None, r["date_raw"], int(r["date_valid"]),
                _weekday_pacific(d) if r["date_valid"] else None,
                r["subject"], r["body_authored"], r["raw_email"], r["mailbox"], r["folder"],
                r["n_recipients"], 1, r["parse_status"]))
            recip_rows.extend((eid, a, t) for a, t in r["recipient_types"].items())
        if len(src_rows) >= BATCH:
            flush()
        if n_files % 50000 == 0:
            print(f"  {n_files:>7} files  {len(seen):>7} unique  {time.time() - t0:5.0f}s", flush=True)
    flush()

    dups = [(n, e) for e, n in seen.items() if n > 1]
    con.executemany("UPDATE emails SET n_copies = ? WHERE email_id = ?", dups)
    con.commit()
    stats = {"source_files": n_files, "parse_failures": n_failed, "unique_emails": len(seen),
             "duplicate_copies": n_files - n_failed - len(seen)}
    print(f"ingest: {stats}  {time.time() - t0:.0f}s")
    return stats


def score_all(con, rules):
    t0 = time.time()
    emails = pd.read_sql_query(
        "SELECT email_id, sender, subject, body_authored, weekday, sent_at_utc FROM emails WHERE date_valid = 1", con)
    rec = pd.read_sql_query(
        "SELECT r.email_id, r.recipient FROM recipients r JOIN emails e USING(email_id) "
        "WHERE e.date_valid = 1", con)
    rec = rec.merge(emails[["email_id", "sender"]], on="email_id")
    pair_counts = rec.groupby(["sender", "recipient"]).size().to_dict()
    sender_counts = emails["sender"].value_counts().to_dict()
    recips_by_email = rec.groupby("email_id")["recipient"].apply(list).to_dict()

    rows = []
    suppressed = 0
    for e in emails.itertuples(index=False):
        wd = None if pd.isna(e.weekday) else int(e.weekday)
        res = score_email(e.subject, e.body_authored, e.sender, recips_by_email.get(e.email_id, []),
                          wd, rules, pair_counts, sender_counts, e.sent_at_utc)
        suppressed += res.suppressed
        if res.flagged:
            rows.append((e.email_id, res.score, res.priority, res.k, res.c, res.t,
                         ",".join(r.rule_id for r in res.reasons), res.reasons_json(),
                         res.not_evaluated_json(), rules.version))
    con.execute("DELETE FROM risk_results")
    con.executemany("INSERT INTO risk_results VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"score: {len(emails)} valid emails scored, {len(rows)} flagged for review, "
          f"{suppressed} language hits suppressed as press/newsletter/bulk sender  {time.time() - t0:.0f}s")
    return {"scored_emails": len(emails), "flagged_emails": len(rows), "suppressed_news": suppressed}


def build_edges(con):
    con.execute("DELETE FROM edges")
    con.execute("""
        INSERT INTO edges
        SELECT e.sender, r.recipient, COUNT(*), MIN(e.sent_at_utc), MAX(e.sent_at_utc)
        FROM recipients r JOIN emails e USING(email_id)
        WHERE e.date_valid = 1 AND e.sender <> '' AND r.recipient LIKE '%@%' AND r.recipient <> e.sender
        GROUP BY e.sender, r.recipient""")
    con.commit()
    return {"edges": con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]}


def build_people(con, rules):
    min_sent = rules.cfg["people"]["min_sent_emails"]
    df = pd.read_sql_query("""
        SELECT e.sender, e.sender_name, r.score, r.rules
        FROM emails e LEFT JOIN risk_results r USING(email_id)
        WHERE e.date_valid = 1 AND e.sender <> ''""", con)
    rows = []
    for sender, g in df.groupby("sender", sort=False):
        flagged = g[g.score.notna()]
        n_sent, n_flag = len(g), len(flagged)
        top_rule = ""
        if n_flag:
            c = Counter(rid for rs in flagged.rules for rid in rs.split(",") if rid.startswith("K-"))
            top_rule = c.most_common(1)[0][0] if c else ""
        rows.append((sender, g.sender_name.mode().iat[0], n_sent, n_flag,
                     round(1000 * n_flag / n_sent, 2), float(flagged.score.max()) if n_flag else 0.0,
                     top_rule, int(n_sent >= min_sent)))
    con.execute("DELETE FROM people")
    con.executemany("INSERT INTO people VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return {"people": len(rows)}


def rescore(db_path, rules_path="config/rules.json"):
    """Re-run scoring, graph and people on an existing database (no re-ingest)."""
    t0 = time.time()
    rules = Rules.load(rules_path)
    con = db.connect(db_path)
    stats = score_all(con, rules)
    stats.update(build_edges(con))
    stats.update(build_people(con, rules))
    db.set_meta(con, rule_version=rules.version, rescored_at=time.strftime("%Y-%m-%d %H:%M:%S"), **stats)
    con.commit()
    con.close()
    print(f"rescore done in {time.time() - t0:.0f}s -> {db_path}")
    return stats


def run(input_path, db_path, rules_path="config/rules.json", limit=None):
    t0 = time.time()
    rules = Rules.load(rules_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suffix):
            print(f"note: replacing existing {db_path + suffix}")
            os.remove(db_path + suffix)
    con = db.connect(db_path)
    db.create(con)
    stats = ingest(con, input_path, limit)
    db.create_indexes(con)
    stats.update(score_all(con, rules))
    stats.update(build_edges(con))
    stats.update(build_people(con, rules))
    v = con.execute("SELECT SUM(date_valid), MIN(sent_at_utc), MAX(sent_at_utc) FROM emails "
                    "WHERE date_valid = 1").fetchone()
    stats.update(valid_dated_emails=v[0], first_date=v[1], last_date=v[2])
    db.set_meta(con, input=os.path.basename(input_path), limit=limit or "none",
                rule_version=rules.version, built_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                runtime_s=round(time.time() - t0), **stats)
    con.commit()
    con.close()
    print(f"pipeline done in {time.time() - t0:.0f}s -> {db_path}")
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="CMU .tar.gz or Kaggle file,email .csv")
    ap.add_argument("--db", default="outputs/enron.db")
    ap.add_argument("--rules", default="config/rules.json")
    ap.add_argument("--limit", type=int, default=None, help="stop after N source files (dev runs)")
    ap.add_argument("--rescore-only", action="store_true",
                    help="re-run scoring/graph/people on an existing --db after editing rules.json")
    args = ap.parse_args()
    if args.rescore_only:
        if not os.path.exists(args.db):
            raise SystemExit(f"Database not found: {args.db}")
        rescore(args.db, args.rules)
        return
    if not args.input or not os.path.exists(args.input):
        raise SystemExit(f"Input not found: {args.input}")
    run(args.input, args.db, args.rules, args.limit)


if __name__ == "__main__":
    main()
