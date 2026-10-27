"""Parser tests. Fixtures are trimmed copies of real messages from the CMU corpus."""
from src.parse import make_email_id, normalize_subject, parse_message

OUTLOOK_REPLY = """Message-ID: <29300756.1075853024176.JavaMail.evans@thyme>
Date: Thu, 27 Sep 2001 06:37:23 -0700 (PDT)
From: gerry.medeles@enron.com
To: lynn.blair@enron.com, bradley.holmes@enron.com
Subject: RE: FAQ's for HotTap
Cc: terry.kowalke@enron.com, john.buchanan@enron.com
Mime-Version: 1.0
Bcc: terry.kowalke@enron.com, john.buchanan@enron.com
X-From: Medeles, Gerry </O=ENRON/OU=NA/CN=RECIPIENTS/CN=GMEDELE>
X-To: Blair, Lynn </O=ENRON/OU=NA/CN=RECIPIENTS/CN=Lblair>

After 2:00 will work with me.  Attached is documentation regarding storage.

 -----Original Message-----
From: \tBlair, Lynn
Sent:\tWednesday, September 26, 2001 3:34 PM
Subject:\tRE: FAQ's for HotTap

\tGerry, do you have some time tomorrow?
"""

LOTUS_FORWARD = """Message-ID: <284087.1075853072307.JavaMail.evans@thyme>
Date: Thu, 7 Jun 2001 12:38:00 -0700 (PDT)
From: lynn.blair@enron.com
To: alma.martinez@enron.com
Subject: Karen Clapper
X-From: Lynn Blair

Alma, hope this helps.  Let me know if you need anything else.  Thanks. Lynn
---------------------- Forwarded by Lynn Blair/ET&S/Enron on 06/07/2001 09:37 AM ---------------------------


Mary Phillips
06/07/2001 09:34 AM
To:\tLynn Blair/ET&S/Enron@ENRON

Karen has a real phobia about spiders.
"""

LOTUS_INLINE = """Message-ID: <10383767.1075853051003.JavaMail.evans@thyme>
Date: Mon, 27 Aug 2001 20:33:30 -0700 (PDT)
From: rick.kile@enron.com
To: charlie.graham@enron.com, lynn.blair@enron.com
Subject: Re: FW: Mt. Jesus Condensate

We probably need someone from operations to go with Oneok to pull this sample.


From:\tCharlie Graham/ENRON@enronXgate on 08/27/2001 01:39 PM
To:\tLynn Blair/ENRON@enronXgate

Oneok has every right to sample the location themselves and should.
"""

DISCLAIMER = """Message-ID: <1.x@thyme>
Date: Thu, 23 Aug 2001 14:43:37 -0700 (PDT)
From: someone@enron.com
To: other@enron.com
Subject: hello

Short note here.

**********************************************************************
This e-mail is the property of Enron Corp. and/or its relevant affiliate and may
contain confidential and privileged material for the sole use of the intended
recipient (s). please contact the sender and delete all copies of the message.
**********************************************************************
"""

BAD = "Subject: no blank line and no date\nFrom:"


def test_outlook_reply_headers_and_split():
    r = parse_message(OUTLOOK_REPLY, "maildir/blair-l/meetings/9.")
    assert r["sender"] == "gerry.medeles@enron.com"
    assert r["sender_name"] == "Medeles, Gerry"
    assert r["recipient_types"] == {"lynn.blair@enron.com": "to", "bradley.holmes@enron.com": "to",
                                    "terry.kowalke@enron.com": "cc", "john.buchanan@enron.com": "cc"}
    # Bcc duplicates Cc in this corpus: no double counting
    assert r["n_recipients"] == 4
    assert r["parse_status"] == "ok"
    assert r["raw_email"].startswith("Message-ID:")
    assert r["date_utc"].isoformat() == "2001-09-27T13:37:23+00:00"
    assert r["date_valid"]
    assert r["body_authored"].startswith("After 2:00")
    assert "do you have some time" not in r["body_authored"]
    assert "do you have some time" in r["body_quoted"]
    assert r["mailbox"] == "blair-l" and r["folder"] == "meetings"
    assert r["subject_norm"] == "faq's for hottap"


def test_lotus_forward_split():
    r = parse_message(LOTUS_FORWARD, "maildir/blair-l/sent_items/396.")
    assert r["body_authored"].endswith("Thanks. Lynn")
    assert "spiders" in r["body_quoted"]


def test_lotus_inline_header_split():
    r = parse_message(LOTUS_INLINE, "maildir/kile-r/inbox/3.")
    assert "pull this sample" in r["body_authored"]
    assert "every right" not in r["body_authored"]


def test_disclaimer_removed_from_authored():
    r = parse_message(DISCLAIMER, "maildir/a-b/inbox/1.")
    assert r["body_authored"] == "Short note here."
    assert "delete" not in r["body_authored"].lower()


def test_malformed_message_does_not_raise():
    r = parse_message(BAD, "maildir/a-b/inbox/2.")
    assert r["date_utc"] is None and not r["date_valid"]
    assert r["recipients"] == []
    assert "bad_date" in r["parse_status"] and "no_recipients" in r["parse_status"]


QP = """Message-ID: <2.x@thyme>
Date: Mon, 2 Apr 2001 09:00:00 -0700 (PDT)
From: a@enron.com
To: b@enron.com
Subject: qp
Content-Transfer-Encoding: quoted-printable

Please delete this e=
mail after reading=20
"""


def test_quoted_printable_decoded():
    r = parse_message(QP, "maildir/a-b/inbox/3.")
    assert "delete this email after reading" in r["body_authored"]


def test_email_id_ignores_folder_and_whitespace():
    a = make_email_id("a@enron.com", "Mon, 1 Jan 2001", "Hi", "body  text\n")
    b = make_email_id("a@enron.com", "Mon, 1 Jan 2001", "Hi", "body text")
    assert a == b
    assert a != make_email_id("a@enron.com", "Mon, 1 Jan 2001", "Hi", "other")
    r1 = parse_message(LOTUS_FORWARD, "maildir/blair-l/sent_items/396.")
    r2 = parse_message(LOTUS_FORWARD, "maildir/blair-l/all_documents/12.")
    assert r1["email_id"] == r2["email_id"]


def test_normalize_subject():
    assert normalize_subject("RE: FW: Re: Deal") == "deal"
