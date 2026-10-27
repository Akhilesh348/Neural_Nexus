"""Score a new email from the command line.

Usage:
    python -m src.check_email path\\to\\message.eml          # raw email with headers
    python -m src.check_email message.eml --json            # machine-readable output

Uses outputs/enron.db (override with --db) for corpus statistics.
"""
import argparse
import json
import sqlite3
from dataclasses import asdict

from src.analyze import analyze_raw
from src.parse import decode
from src.scoring import Rules


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="raw email file (headers, blank line, body)")
    ap.add_argument("--db", default="outputs/enron.db")
    ap.add_argument("--rules", default="config/rules.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.file, "rb") as f:
        raw = decode(f.read())
    rules = Rules.load(args.rules)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rec, res = analyze_raw(raw, con, rules)

    if args.json:
        print(json.dumps({"flagged": res.flagged, "suppressed": res.suppressed, "score": res.score,
                          "priority": res.priority, "k": res.k, "c": res.c, "t": res.t,
                          "reasons": [asdict(r) for r in res.reasons],
                          "not_evaluated": [asdict(r) for r in res.not_evaluated],
                          "rule_version": rules.version}, indent=2))
        return
    print(f"From: {rec['sender']}  To: {', '.join(rec['recipients']) or '-'}  Subject: {rec['subject']}")
    if res.flagged:
        print(f"FLAGGED FOR REVIEW  score {res.score:.0f}/100  ({res.priority} priority)  "
              f"K {res.k:.0f} + C {res.c:.0f} + T {res.t:.0f}  rules v{rules.version}")
        for r in res.reasons:
            print(f"  +{r.points:<3.0f}{r.rule_id:<14}{r.explanation}")
            if r.evidence_excerpt:
                print(f"       evidence: \"{r.evidence_excerpt}\"")
            elif r.supporting_value:
                print(f"       detail:   {r.supporting_value}")
    elif res.suppressed:
        print("NOT FLAGGED: suspicious phrase found but the text looks like a press article, newsletter or bulk sender")
    else:
        print("NOT FLAGGED: no language rule fired on the sender's own words (context alone never flags)")
    for r in res.not_evaluated:
        print(f"  not evaluated  {r.rule_id}: {r.explanation}")


if __name__ == "__main__":
    main()
