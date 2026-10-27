"""Human-review precision workflow.

1) Build the annotation sheet (top 20 ranked + 20 seeded random from the rest of the flagged list):
       python -m src.evaluate template --db outputs/enron.db --out docs/ANNOTATION_TEMPLATE.csv
2) Each reviewer copies the sheet, fills review_label (yes / no / ambiguous) independently.
3) Compute metrics from the filled sheets (never from the heuristics themselves):
       python -m src.evaluate score --labels data/labels_reviewerA.csv [data/labels_reviewerB.csv]

Rubric: "Would a compliance reviewer reasonably want to read this email next, based on
its observable content and context?" This is review-worthiness, not wrongdoing.
"""
import argparse
import json
import sqlite3

import pandas as pd

RANKING_SQL = """
SELECT r.email_id, r.score, r.priority, r.rules, r.reasons_json, e.sent_at_utc, e.sender, e.subject
FROM risk_results r JOIN emails e USING(email_id)
ORDER BY r.score DESC, LENGTH(r.rules) DESC, e.sent_at_utc DESC
"""  # same order as the dashboard
LABELS = {"yes", "no", "ambiguous"}


def build_template(db_path, out, top_k=20, n_random=20, seed=42):
    ranked = pd.read_sql_query(RANKING_SQL, sqlite3.connect(db_path))
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    top = ranked.head(top_k).assign(sample=f"top{top_k}")
    rest = ranked.iloc[top_k:]
    rnd = rest.sample(n=min(n_random, len(rest)), random_state=seed).assign(sample="random")
    sheet = pd.concat([top, rnd])
    sheet["evidence"] = sheet.reasons_json.apply(
        lambda s: " | ".join(r["evidence_excerpt"][:200] for r in json.loads(s) if r.get("evidence_excerpt")))
    sheet = sheet[["sample", "rank", "email_id", "score", "rules", "sent_at_utc", "sender", "subject", "evidence"]]
    sheet["review_label"] = ""
    sheet["reviewer"] = ""
    sheet["reviewer_note"] = ""
    sheet.to_csv(out, index=False, encoding="utf-8")
    print(f"wrote {len(sheet)} rows to {out} (top {len(top)}, random {len(rnd)}, seed {seed})")


def _precision(df):
    lab = df.review_label
    yes, no, amb = int((lab == "yes").sum()), int((lab == "no").sum()), int((lab == "ambiguous").sum())
    unlabeled = int((~lab.isin(LABELS)).sum())
    decisive = yes + no
    out = {"n": len(df), "yes": yes, "no": no, "ambiguous": amb, "unlabeled": unlabeled,
           "yes_over_decisive": round(yes / decisive, 3) if decisive else None}
    out["precision"] = round(yes / len(df), 3) if (amb == 0 and unlabeled == 0 and len(df)) else None
    if out["precision"] is None:
        out["status"] = "pending adjudication / labeling"
    return out


def score_labels(paths, out="outputs/metrics.json"):
    sheets = []
    for p in paths:
        s = pd.read_csv(p, dtype=str).fillna("")
        s["review_label"] = s.review_label.str.strip().str.lower()
        s["score"] = s.score.astype(float)
        sheets.append(s)
    first = sheets[0]
    if (first.review_label == "").all():
        raise SystemExit("No labels filled in yet — precision cannot be computed.")
    top = first[first["sample"].str.startswith("top")]
    metrics = {
        "label_file": paths[0],
        "rubric": "Would a compliance reviewer reasonably want to read this email next?",
        "precision_at_%d" % len(top): _precision(top),
        "random_flagged_sample": _precision(first[first["sample"] == "random"]),
        "per_rule": {},
    }
    exploded = first.assign(rule=first.rules.str.split(",")).explode("rule")
    for rule, g in exploded.groupby("rule"):
        metrics["per_rule"][rule] = _precision(g)
    if len(sheets) > 1:
        a, b = sheets[0].set_index("email_id").review_label, sheets[1].set_index("email_id").review_label
        both = a.index.intersection(b.index)
        both = [i for i in both if a[i] in LABELS and b[i] in LABELS]
        agree = sum(a[i] == b[i] for i in both)
        metrics["inter_reviewer_agreement"] = {"compared": len(both), "agreed": agree,
                                               "rate": round(agree / len(both), 3) if both else None,
                                               "second_label_file": paths[1]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(json.dumps(metrics, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template")
    t.add_argument("--db", default="outputs/enron.db")
    t.add_argument("--out", default="docs/ANNOTATION_TEMPLATE.csv")
    t.add_argument("--seed", type=int, default=42)
    s = sub.add_parser("score")
    s.add_argument("--labels", nargs="+", required=True)
    s.add_argument("--out", default="outputs/metrics.json")
    args = ap.parse_args()
    if args.cmd == "template":
        build_template(args.db, args.out, seed=args.seed)
    else:
        score_labels(args.labels, args.out)


if __name__ == "__main__":
    main()
