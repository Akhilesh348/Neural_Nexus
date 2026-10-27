import pandas as pd

from src.evaluate import _precision


def sheet(labels):
    return pd.DataFrame({"review_label": labels})


def test_precision_only_when_all_decisive():
    assert _precision(sheet(["yes"] * 15 + ["no"] * 5))["precision"] == 0.75


def test_ambiguous_keeps_precision_pending():
    m = _precision(sheet(["yes"] * 14 + ["no"] * 5 + ["ambiguous"]))
    assert m["precision"] is None and m["status"].startswith("pending")
    assert m["yes_over_decisive"] == round(14 / 19, 3) and m["ambiguous"] == 1


def test_unlabeled_rows_are_counted():
    m = _precision(sheet(["yes", ""]))
    assert m["unlabeled"] == 1 and m["precision"] is None
