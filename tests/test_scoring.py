"""Scoring rule tests (synthetic sentences, not dataset results)."""
import pytest

from src.scoring import Rules, score_email


@pytest.fixture(scope="module")
def rules():
    return Rules.load("config/rules.json")


def s(rules, body, sender="a@enron.com", recips=("b@enron.com",), weekday=2, subject="", pairs=None, counts=None):
    return score_email(subject, body, sender, list(recips), weekday, rules, pairs, counts)


@pytest.mark.parametrize("body,rule", [
    ("Please shred the old trading files today.", "K-DESTROY"),
    ("Destroy all documents related to the deal.", "K-DESTROY"),
    ("Delete this email after you read it.", "K-DESTROY"),
    ("Keep this between us for now.", "K-SECRECY"),
    ("Please don't forward this to anyone.", "K-SECRECY"),
    ("Do not put this in writing again.", "K-NO-RECORD"),
])
def test_strong_phrases_flag(rules, body, rule):
    r = s(rules, body)
    assert r.flagged and rule in [x.rule_id for x in r.reasons]
    assert r.score == 30 and r.priority == "medium"
    ev = [x for x in r.reasons if x.rule_id == rule][0]
    assert ev.evidence_excerpt and ev.supporting_value.lower() in ev.evidence_excerpt.lower()


@pytest.mark.parametrize("body", [
    "This is confidential and proprietary information.",          # weak word only
    "I moved it to my Deleted Items folder.",                       # folder name
    "If you are not the intended recipient, please delete this email.",  # disclaimer
    "Your mailbox is full, please delete these messages to free space.",  # IT notice
    "The LJM2 partnership meeting is on Tuesday.",                  # topic alone
    "",
    # false positives seen on real data (paraphrased), fixed in rule_version 1.0.0
    "If you received this in error, please contact the sender and\ndelete this e-mail, including attachments.",
    "Lawyers alternately praised and shredded them in the hearing.",
    "Please don't delete any e-mails until the audit is complete.",
    "Please do not forward this link to anyone else, as it is unique for each respondent.",
    "I was told that I should not delete any e-mails until further notice.",
])
def test_no_flag_without_strong_language(rules, body):
    assert not s(rules, body).flagged


def test_context_alone_never_flags(rules):
    r = s(rules, "Lunch on Saturday?", recips=["x@hotmail.com"], weekday=6,
          pairs={}, counts={"a@enron.com": 500})
    assert not r.flagged and r.score == 0


def test_amplifiers_add_only_when_flagged_and_cap(rules):
    body = "Shred the files. Keep this between us. Do not put this in writing. LJM details attached."
    r = s(rules, body, recips=["x@hotmail.com"], weekday=6,
          pairs={("a@enron.com", "x@hotmail.com"): 1}, counts={"a@enron.com": 500})
    ids = {x.rule_id for x in r.reasons}
    assert {"K-DESTROY", "K-SECRECY", "K-NO-RECORD", "K-TOPIC", "C-EXTERNAL", "C-RARE-PAIR", "T-WEEKEND"} <= ids
    assert r.k == 60 and r.c == 30 and r.t == 10
    assert r.score == 100 and r.priority == "high"


def test_missing_data_is_not_evaluated_not_zero(rules):
    r = s(rules, "Shred it all. Shred the documents.", weekday=None, pairs={}, counts={"a@enron.com": 3})
    ne = {x.rule_id for x in r.not_evaluated}
    assert {"T-OFF-HOURS", "T-WEEKEND", "C-RARE-PAIR"} <= ne


def test_subdomain_is_internal(rules):
    r = s(rules, "Shred the files.", recips=["x@mailman.enron.com"])
    assert "C-EXTERNAL" not in {x.rule_id for x in r.reasons}


def test_press_article_is_not_flagged_but_recorded(rules):
    body = ("Andersen Destroyed Documents, The Wall Street Journal reported. The auditor shredded "
            "papers related to the audit. Copyright 2002 Dow Jones & Company. All rights reserved.")
    r = s(rules, body)
    assert not r.flagged and r.suppressed
    assert "N-NEWS" in {x.rule_id for x in r.not_evaluated}


def test_short_internal_mention_of_newspaper_still_flags(rules):
    r = s(rules, "Saw the Wall Street Journal piece. Shred the old files before Monday.")
    assert r.flagged


def test_deterministic(rules):
    a = s(rules, "Keep this quiet. Shred the files.")
    b = s(rules, "Keep this quiet. Shred the files.")
    assert a.reasons_json() == b.reasons_json() and a.score == b.score
