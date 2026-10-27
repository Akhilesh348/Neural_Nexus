"""Explainable review-priority scoring (not a probability of wrongdoing).

score = min(100, K + C + T), computed only for emails where a language rule fired.
Each phrase has a strength (strong / medium / weak) and each rule contributes its
strongest hit. Every point comes with a reason and, where applicable, the exact
sentence that produced it.
"""
import json
import re
from dataclasses import asdict, dataclass, field
from typing import List

# A sentence ends at . ! ? or a blank line; single line breaks are just wrapping.
_SENTENCE_END = re.compile(r"[.!?]|\n[ \t]*\n")


@dataclass
class Reason:
    rule_id: str
    points: float
    explanation: str
    supporting_value: str = ""
    evidence_excerpt: str = ""


@dataclass
class ScoreResult:
    flagged: bool
    suppressed: bool = False   # language hit, but press/newsletter text or a bulk sender
    score: float = 0.0
    priority: str = "not flagged"
    k: float = 0.0
    c: float = 0.0
    t: float = 0.0
    reasons: List[Reason] = field(default_factory=list)
    not_evaluated: List[Reason] = field(default_factory=list)

    def reasons_json(self):
        return json.dumps([asdict(r) for r in self.reasons])

    def not_evaluated_json(self):
        return json.dumps([asdict(r) for r in self.not_evaluated])


class Rules:
    """Compiled view of config/rules.json."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.version = cfg["rule_version"]
        lang = cfg["language"]
        self.k_cap = lang["cap"]
        self.exclusions = re.compile("|".join(lang["context_exclusions"]), re.I)
        self.window = lang["context_window_chars"]
        self.negation = re.compile(lang["negation_pattern"], re.I)
        self.neg_window = lang["negation_window_chars"]
        # (rule_id, explanation, check_negation, [(compiled, points, strength), ...])
        self.strong = [(r["id"], r["explanation"], r.get("check_negation", False),
                        [(re.compile(p["pattern"], re.I), p["points"], p["strength"]) for p in r["patterns"]])
                       for r in lang["strong_rules"]]
        n = lang["news_suppression"]
        self.news = (n["id"], n["explanation"], re.compile("|".join(n["markers"]), re.I),
                     n["min_markers"], n["single_marker_min_chars"])
        b = lang["bulk_sender_suppression"]
        self.bulk = (b["id"], b["explanation"], re.compile("|".join(b["sender_patterns"]), re.I))
        t = lang["topic_rule"]
        self.topic = (t["id"], t["explanation"], t["points"], re.compile("|".join(t["patterns"]), re.I))
        com = cfg["communication"]
        self.internal = tuple(d.lower() for d in com["internal_domains"])
        self.c_cap = com["cap"]
        self.ext, self.rare, self.narrow = com["external"], com["rare_pair"], com["narrow"]
        tim = cfg["timing"]
        self.t_cap = tim["cap"]
        self.weekend, self.off_hours = tim["weekend"], tim["off_hours"]
        self.bands = cfg["priority_bands"]

    @classmethod
    def load(cls, path="config/rules.json"):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def is_internal(self, addr):
        dom = addr.rsplit("@", 1)[-1] if "@" in addr else ""
        return any(dom == d or dom.endswith("." + d) for d in self.internal)

    def priority(self, score):
        if score >= self.bands["high"]:
            return "high"
        if score >= self.bands["medium"]:
            return "medium"
        return "low"


def sentence_around(text, start, end, max_len=300):
    """The sentence containing text[start:end], trimmed to max_len."""
    s = 0
    for b in _SENTENCE_END.finditer(text, 0, start):
        s = b.end()
    b = _SENTENCE_END.search(text, end)
    e = b.end() if b else len(text)
    sent = " ".join(text[s:e].split())
    if len(sent) > max_len:
        mid = (start - s)
        lo = max(0, mid - max_len // 2)
        sent = "…" + sent[lo:lo + max_len] + "…"
    return sent


def looks_like_news(text, rules):
    """Press articles / newsletters: >= min_markers distinct markers, or one marker in a long text."""
    _, _, rx, min_markers, long_chars = rules.news
    found = {m.group(0).lower() for m in rx.finditer(text)}
    return len(found) >= min_markers or (len(found) == 1 and len(text) >= long_chars)


def language_hits(text, rules):
    """Strongest valid hit per rule: [(rule_id, explanation, points, strength, matched, sentence)]."""
    hits = []
    for rid, why, check_neg, patterns in rules.strong:
        best = None
        for rx, pts, strength in patterns:
            if best and pts <= best[2]:
                continue
            for m in rx.finditer(text):
                # Disclaimers wrap over several lines, so check a character window, not one line.
                ctx = text[max(0, m.start() - rules.window): m.end() + rules.window // 2]
                if rules.exclusions.search(ctx):
                    continue
                if check_neg and rules.negation.search(text[max(0, m.start() - rules.neg_window): m.start()]):
                    continue
                best = (rid, why, pts, strength, m.group(0), sentence_around(text, m.start(), m.end()))
                break
        if best:
            hits.append(best)
    return hits


def off_hours_share(hour, counts, window):
    """Share of a sender's emails sent within +/-window hours of `hour` (circular 24 h)."""
    total = sum(counts)
    near = sum(counts[(hour + d) % 24] for d in range(-window, window + 1))
    return near / total, total


def score_email(subject, body_authored, sender, recipients, weekday, rules,
                pair_counts=None, sender_counts=None, sent_date=None, hour=None, sender_hours=None):
    """Score one email.

    weekday: 0=Mon..6=Sun, or None when the date is invalid (timing not evaluated).
    sent_date: 'YYYY-MM-DD' or None (kept for callers; no date-window rule is applied).
    hour: header hour 0-23 (UTC); sender_hours: {sender: [24 counts]} over the corpus.
    pair_counts: {(sender, recipient): n}; sender_counts: {sender: n} over the corpus.
    """
    text = f"{subject or ''}\n{body_authored or ''}"
    res = ScoreResult(flagged=False)

    hits = language_hits(text, rules)
    if not hits:
        return res  # language is required: context alone never flags an email

    found = ", ".join(h[0] for h in hits)
    if rules.bulk[2].search(sender or ""):
        res.not_evaluated.append(Reason(rules.bulk[0], 0, rules.bulk[1], found, hits[0][5]))
        res.suppressed = True
        return res
    if looks_like_news(text, rules):
        res.not_evaluated.append(Reason(rules.news[0], 0, rules.news[1], found, hits[0][5]))
        res.suppressed = True
        return res
    res.flagged = True

    # K: language
    k = 0
    for rid, why, pts, strength, matched, sent in hits:
        k += pts
        res.reasons.append(Reason(rid, pts, f"{why} ({strength} phrase)", matched, sent))
    tid, twhy, tpts, trx = rules.topic
    m = trx.search(text)
    if m:
        k += tpts
        res.reasons.append(Reason(tid, tpts, twhy, m.group(0), sentence_around(text, m.start(), m.end())))
    res.k = min(k, rules.k_cap)

    # C: communication
    c = 0
    if rules.is_internal(sender):
        external = [r for r in recipients if "@" in r and not rules.is_internal(r)]
        if external:
            c += rules.ext["points"]
            res.reasons.append(Reason(rules.ext["id"], rules.ext["points"], rules.ext["explanation"],
                                      ", ".join(external[:5])))
    if pair_counts is not None and sender_counts is not None:
        if sender_counts.get(sender, 0) >= rules.rare["min_sender_emails"]:
            rare = [r for r in recipients if pair_counts.get((sender, r), 0) <= rules.rare["max_pair_emails"]]
            if rare:
                c += rules.rare["points"]
                res.reasons.append(Reason(rules.rare["id"], rules.rare["points"], rules.rare["explanation"],
                                          ", ".join(rare[:5])))
        else:
            res.not_evaluated.append(Reason(rules.rare["id"], 0,
                                            f"Not evaluated: sender has fewer than {rules.rare['min_sender_emails']} emails"))
    if 1 <= len(recipients) <= rules.narrow["max_recipients"]:
        c += rules.narrow["points"]
        res.reasons.append(Reason(rules.narrow["id"], rules.narrow["points"], rules.narrow["explanation"],
                                  f"{len(recipients)} recipient(s)"))
    res.c = min(c, rules.c_cap)

    # T: timing
    t = 0
    if weekday is None:
        res.not_evaluated.append(Reason(rules.weekend["id"], 0, "Not evaluated: no valid date"))
    elif weekday >= 5:
        t += rules.weekend["points"]
        res.reasons.append(Reason(rules.weekend["id"], rules.weekend["points"], rules.weekend["explanation"],
                                  ["Sat", "Sun"][weekday - 5]))
    oh = rules.off_hours
    counts = (sender_hours or {}).get(sender)
    if hour is None or sender_hours is None:
        res.not_evaluated.append(Reason(oh["id"], 0, "Not evaluated: no valid date"))
    elif not counts or sum(counts) < oh["min_sender_emails"]:
        res.not_evaluated.append(Reason(oh["id"], 0, f"Not evaluated: sender has fewer than "
                                                     f"{oh['min_sender_emails']} dated emails"))
    else:
        share, total = off_hours_share(hour, counts, oh["window_hours"])
        if share <= oh["max_share"]:
            t += oh["points"]
            res.reasons.append(Reason(oh["id"], oh["points"], oh["explanation"],
                                      f"header hour {hour:02d} UTC: only {share:.1%} of this sender's "
                                      f"{total} emails fall within +/-{oh['window_hours']} h"))
    res.t = min(t, rules.t_cap)

    res.score = float(min(100, res.k + res.c + res.t))
    res.priority = rules.priority(res.score)
    return res
