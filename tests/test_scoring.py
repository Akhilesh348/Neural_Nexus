"""Scoring rule tests (synthetic sentences, not dataset results)."""
import pytest

from src.scoring import Rules, score_email

INTERNAL_MANY = [f"p{i}@enron.com" for i in range(10)]  # 10 internal recipients: no C-NARROW


@pytest.fixture(scope="module")
def rules():
    return Rules.load("config/rules.json")


def s(rules, body, sender="a@enron.com", recips=INTERNAL_MANY, weekday=2, subject="",
      pairs=None, counts=None, date="2001-03-07"):
    return score_email(subject, body, sender, list(recips), weekday, rules, pairs, counts, date)


@pytest.mark.parametrize("body,rule,points", [
    ("Please shred the old trading files today.", "K-DESTROY", 40),
    ("Destroy all documents related to the deal.", "K-DESTROY", 40),
    ("Delete this email after you read it.", "K-DESTROY", 15),
    ("I would like to take this risk off the books.", "K-OFF-BOOKS", 40),
    ("Do not put this in writing again.", "K-NO-RECORD", 40),
    ("Keep this between us for now.", "K-SECRECY", 25),
    ("Between you and me, the number is lower.", "K-SECRECY", 25),
    ("Please don't forward this to anyone.", "K-SECRECY", 15),
    ("(Please keep this confidential) He called me in to tell me.", "K-SECRECY", 25),
    ("Do not discuss this with anyone at CES please.", "K-SECRECY", 25),
    ("I'd prefer not to put this in writing yet.", "K-NO-RECORD", 40),
    ("I would rather discuss this in person.", "K-NO-RECORD", 15),
])
def test_phrase_strengths(rules, body, rule, points):
    r = s(rules, body)
    assert r.flagged
    hit = [x for x in r.reasons if x.rule_id == rule][0]
    assert hit.points == points and r.k == points
    assert hit.evidence_excerpt and hit.supporting_value.lower() in hit.evidence_excerpt.lower()


def test_strongest_hit_per_rule_counts_once(rules):
    r = s(rules, "Delete this email. Also shred the files.")
    assert [x.points for x in r.reasons if x.rule_id == "K-DESTROY"] == [40]


def test_priority_bands(rules):
    assert s(rules, "Please don't forward this.").priority == "low"            # 15
    assert s(rules, "Shred the files.").priority == "medium"                    # 40
    assert s(rules, "Shred the files. Keep this quiet.").priority == "high"     # 65 -> capped K 60


@pytest.mark.parametrize("body", [
    "This is confidential and proprietary information.",          # weak word only
    "I moved it to my Deleted Items folder.",                       # folder name
    "If you are not the intended recipient, please delete this email.",  # disclaimer
    "Your mailbox is full, please delete these messages to free space.",  # IT notice
    "The LJM2 partnership meeting is on Tuesday.",                  # topic alone
    "",
    # false positives seen on real data (paraphrased)
    "If you received this in error, please contact the sender and\ndelete this e-mail, including attachments.",
    "Lawyers alternately praised and shredded them in the hearing.",
    "Please don't delete any e-mails until the audit is complete.",
    "Please do not forward this link to anyone else, as it is unique for each respondent.",
    "I was told that I should not delete any e-mails until further notice.",
    "She says all trades have rolled off the books.",
    "If there is one shred of evidence that he raised a red flag, show me.",
    "Can we arrange a call between you and me and Remy to discuss?",
    "Verify that your calendar was imported correctly, and then delete this message.",
    "This press report is not for distribution within or without an organization.",
    "Document shredding has been reported at the auditor.",                  # topic only
])
def test_no_flag(rules, body):
    assert not s(rules, body).flagged


def test_spam_offer_is_suppressed(rules):
    body = ("As an Elite Member, we have hand picked this special offer just for you. "
            "(Please don't share it with anyone else).")
    r = s(rules, body, sender="betatest@offers.example")
    assert not r.flagged and r.suppressed


def test_bulk_sender_suppressed(rules):
    r = s(rules, "Please do not share this number with anyone!", sender="specialdeals@lists.em5000.com")
    assert not r.flagged and r.suppressed
    assert "N-BULK" in {x.rule_id for x in r.not_evaluated}


def test_context_alone_never_flags(rules):
    r = s(rules, "Lunch on Saturday?", recips=["x@hotmail.com"], weekday=6, date="2001-11-03",
          pairs={}, counts={"a@enron.com": 500})
    assert not r.flagged and r.score == 0


def test_all_amplifiers_and_caps(rules):
    body = "Shred the files. Keep this between us. Do not put this in writing. LJM details attached."
    r = s(rules, body, recips=["x@hotmail.com"], weekday=6, date="2001-11-03",
          pairs={("a@enron.com", "x@hotmail.com"): 1}, counts={"a@enron.com": 500})
    ids = {x.rule_id for x in r.reasons}
    assert {"K-DESTROY", "K-SECRECY", "K-NO-RECORD", "K-TOPIC", "C-EXTERNAL", "C-RARE-PAIR",
            "C-NARROW", "T-WEEKEND"} <= ids
    assert r.k == 60 and r.c == 30 and r.t == 5
    assert r.score == 95 and r.priority == "high"


def test_no_date_window_bonus(rules):
    a = s(rules, "Shred the files.", date="2001-11-05")
    b = s(rules, "Shred the files.", date="2000-11-06")
    assert a.score == b.score


def test_missing_data_is_not_evaluated_not_zero(rules):
    r = s(rules, "Shred the documents.", weekday=None, date=None, pairs={}, counts={"a@enron.com": 3})
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
    assert s(rules, "Saw the Wall Street Journal piece. Shred the old files before Monday.").flagged


def test_sec_topic_is_case_sensitive(rules):
    assert "K-TOPIC" in {x.rule_id for x in s(rules, "Shred the files before the SEC asks.").reasons}
    assert "K-TOPIC" not in {x.rule_id for x in s(rules, "Shred the files, back in a sec.").reasons}


def test_deterministic(rules):
    a = s(rules, "Keep this quiet. Shred the files.")
    b = s(rules, "Keep this quiet. Shred the files.")
    assert a.reasons_json() == b.reasons_json() and a.score == b.score
