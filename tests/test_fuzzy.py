from jfterm.fuzzy import rank, score


def test_score_no_match_returns_none():
    assert score("xyz", "project") is None


def test_score_empty_query_is_zero():
    assert score("", "anything") == 0


def test_score_intellij_initials_lowercase():
    s = score("panst", "Project A: New Shell Tab")
    assert s is not None
    s_mid = score("panst", "panastic")
    assert s_mid is None or s > s_mid


def test_score_intellij_initials_uppercase():
    assert score("PANST", "Project A: New Shell Tab") is not None
    assert score("PANST", "panastic") is None


def test_rank_orders_by_score_descending():
    items = ["panastic", "Project A: New Shell Tab", "Pat A: Nest"]
    out = rank("panst", items, key=lambda s: s)
    assert out[0] == "Project A: New Shell Tab"


def test_rank_drops_unmatched():
    out = rank("zzz", ["abc", "def"], key=lambda s: s)
    assert out == []
