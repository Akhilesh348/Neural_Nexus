"""Explainable review-priority scoring (not a probability of wrongdoing).

score = min(100, K + C + T), computed only for emails where a strong language
rule fired. Every point comes with a reason and, where applicable, the exact
sentence that produced it.
"""
import json
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

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
    suppressed: bool = False   # language hit, but text is press/newsletter content
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
        self.k_points = lang["points_per_strong_rule"]
        self.k_cap = lang["cap"]
        self.exclusions = re.compile("|".join(lang["context_exclusions"]), re.I)
        self.window = lang["context_window_chars"]
        self.negation = re.compile(lang["negation_pattern"], re.I)
        self.neg_window = lang["negation_window_chars"]
        self.strong = [(r["id"], r["explanation"], re.compile("|".join(r["patterns"]), re.I),
                        r.get("check_negation", False))
                       for r in lang["strong_rules"]]
        n = lang["news_suppression"]
        self.news = (n["id"], n["explanation"], re.compile("|".join(n["markers"]), re.I),
                     n["min_markers"], n["single_marker_min_chars"])
        t = lang["topic_rule"]
        self.topic = (t["id"], t["explanation"], t["points"], re.compile("|".join(t["patterns"]), re.I))
        com = cfg["communication"]
        self.internal = tuple(d.lower() for d in com["internal_domains"])
        self.c_cap = com["cap"]
        self.ext = com["external"]
        self.rare = com["rare_pair"]
        self.weekend = cfg["timing"]["weekend"]
        self.hour_rule = cfg["timing"]["hour_rule"]
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
    """Strong-rule hits as [(rule_id, explanation, matched, sentence)], one per rule."""
    hits = []
    for rid, why, rx, check_neg in rules.strong:
        for m in rx.finditer(text):
            # Disclaimers wrap over several lines, so check a character window, not one line.
            ctx = text[max(0, m.start() - rules.window): m.end() + rules.window // 2]
            if rules.exclusions.search(ctx):
                continue
            if check_neg and rules.negation.search(text[max(0, m.start() - rules.neg_window): m.start()]):
                continue
            sent = sentence_around(text, m.start(), m.end())
            hits.append((rid, why, m.group(0), sent))
            break  # one hit per rule is enough evidence
    return hits


def score_email(subject, body_authored, sender, recipients, weekday, rules,
                pair_counts=None, sender_counts=None):
    """Score one email.

    weekday: 0=Mon..6=Sun, or None when the date is invalid (timing not evaluated).
    pair_counts: {(sender, recipient): n}; sender_counts: {sender: n} over the corpus.
    """
    text = f"{subject or ''}\n{body_authored or ''}"
    res = ScoreResult(flagged=False)
    res.not_evaluated.append(Reason(rules.hour_rule["id"], 0, rules.hour_rule["explanation"]))

    hits = language_hits(text, rules)
    if not hits:
        return res  # K is required: context alone never flags an email
    if looks_like_news(text, rules):
        nid, nwhy = rules.news[0], rules.news[1]
        res.not_evaluated.append(Reason(nid, 0, nwhy, ", ".join(h[0] for h in hits), hits[0][3]))
        res.suppressed = True
        return res
    res.flagged = True

    k = 0
    for rid, why, matched, sent in hits:
        k += rules.k_points
        res.reasons.append(Reason(rid, rules.k_points, why, matched, sent))
    tid, twhy, tpts, trx = rules.topic
    m = trx.search(text)
    if m:
        k += tpts
        res.reasons.append(Reason(tid, tpts, twhy, m.group(0), sentence_around(text, m.start(), m.end())))
    res.k = min(k, rules.k_cap)

    c = 0
    sender_internal = rules.is_internal(sender)
    external = [r for r in recipients if "@" in r and not rules.is_internal(r)]
    if sender_internal and external:
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
    res.c = min(c, rules.c_cap)

    if weekday is None:
        res.not_evaluated.append(Reason(rules.weekend["id"], 0, "Not evaluated: no valid date"))
        res.t = 0
    elif weekday >= 5:
        res.t = rules.weekend["points"]
        res.reasons.append(Reason(rules.weekend["id"], res.t, rules.weekend["explanation"],
                                  ["Sat", "Sun"][weekday - 5]))

    res.score = float(min(100, res.k + res.c + res.t))
    res.priority = rules.priority(res.score)
    return res
