"""End-to-end smoke test on a tiny synthetic tarball (never shown as real results)."""
import io
import sqlite3
import tarfile

from src import db
from src.pipeline import run
from src.scoring import Rules

MSG = """Message-ID: <{mid}@thyme>
Date: {date}
From: {frm}
To: {to}
Subject: {subj}
X-From: Test User
X-Folder: \\x\\{folder}

{body}
"""


def _tar(path, files):
    with tarfile.open(path, "w:gz") as tf:
        for name, text in files:
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_pipeline_end_to_end(tmp_path):
    flagged = dict(date="Sat, 5 May 2001 10:00:00 -0700 (PDT)", frm="a@enron.com",
                   to="b@enron.com, x@hotmail.com", subj="files", body="Please shred the files.")
    plain = dict(date="Mon, 7 May 2001 10:00:00 -0700 (PDT)", frm="b@enron.com",
                 to="a@enron.com", subj="lunch", body="Lunch at noon?")
    bogus = dict(date="Mon, 1 Jan 1979 10:00:00 -0800 (PST)", frm="c@enron.com",
                 to="a@enron.com", subj="old", body="Shred everything.")
    files = [
        ("maildir/a-x/sent/1.", MSG.format(mid=1, folder="sent", **flagged)),
        ("maildir/a-x/all_documents/7.", MSG.format(mid=2, folder="all_documents", **flagged)),  # duplicate copy
        ("maildir/b-y/inbox/1.", MSG.format(mid=3, folder="inbox", **plain)),
        ("maildir/c-z/inbox/1.", MSG.format(mid=4, folder="inbox", **bogus)),
    ]
    tar = tmp_path / "mini.tar.gz"
    _tar(tar, files)
    dbp = str(tmp_path / "t.db")
    stats = run(str(tar), dbp)

    assert stats["source_files"] == 4 and stats["unique_emails"] == 3 and stats["duplicate_copies"] == 1
    assert stats["flagged_emails"] == 1  # 1979 email excluded from scoring (invalid date)

    con = sqlite3.connect(dbp)
    eid, score = con.execute("SELECT email_id, score FROM risk_results").fetchone()
    ev = db.email_evidence(con, eid)
    assert ev["email"]["subject"] == "files"
    assert "shred the files" in ev["email"]["raw_email"]
    assert len(ev["sources"]) == 2 and ev["email"]["n_copies"] == 2
    assert {r["recipient"] for r in ev["recipients"]} == {"b@enron.com", "x@hotmail.com"}
    assert "C-EXTERNAL" in ev["risk"]["rules"] and "T-WEEKEND" in ev["risk"]["rules"]
    assert score == 30 + 15 + 10
    # graph counts the duplicate once
    assert con.execute("SELECT n_emails FROM edges WHERE sender='a@enron.com' AND recipient='b@enron.com'"
                       ).fetchone()[0] == 1
    assert con.execute("SELECT n_flagged FROM people WHERE sender='a@enron.com'").fetchone()[0] == 1
    assert db.get_meta(con)["rule_version"] == Rules.load().version
