"""When the page's list call names its account in a way this app cannot
read (#248), the stop says which way, in counts and yes or no, in the
failure file and in Diagnose, and never a name or a value. Every value is
invented."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import bofa_docs as app_mod
import bofa_site as site
import standin_bank as sb
from paperpull_core import pressing
from paperpull_core.failure import _step
from paperpull_core.words import shape_tree

KEY = sb.KEY
GOOD_BODY = {KEY: "K-ALPHA-0001", "docCategoryId": "CAT-STMT", "lang": "en", "year": "2026"}
SECRETS = ("K-ALPHA-0001", "K-BRAVO-0002", "ZZ-INVENTED-9", "K-OTHER-7777", "zqxHandle",
           KEY, "Everyday Checking", "Travel Card", "12345678", "Dana")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    site.forget()
    monkeypatch.setattr(pressing, "click", sb.press)
    yield
    site.forget()


def accounts(*selected, **changes):
    found = copy.deepcopy(sb.ACCOUNTS)
    for a, s in zip(found, selected):
        a["selected"] = s
    for i, change in changes.items():
        found[int(i[1:])].update(change)
    return found


def bank(body=None, listed_accounts=None):
    page = sb.Bank()
    if body is not None:
        page.first_body = body
    if listed_accounts is not None:
        page.listed = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")], listed_accounts)
    return page


def stopped(page):
    with pytest.raises(site.NotLearned) as e:
        site.learn(page)
    return e.value


# The four ways, and the facts each leaves.
WAYS = {
    "no other field": (dict(body={"docCategoryId": "CAT-STMT", "year": "2026", "lang": "en"}),
                       {"other_list_fields": 0, "list_fields_found": 3}),
    "two other fields": (dict(body=dict(GOOD_BODY, zqxHandle="ZZ-INVENTED-9")),
                         {"other_list_fields": 2, "other_fields_also_in_an_account": 1}),
    "a number": (dict(body=dict(GOOD_BODY, **{KEY: 12345678})),
                 {"other_list_fields": 1, "account_field_is_text": False,
                  "accounts_with_the_same_text": 0}),
    "a list": (dict(body=dict(GOOD_BODY, **{KEY: ["K-ALPHA-0001"]})),
               {"account_field_is_text": False}),
    "nothing": (dict(body=dict(GOOD_BODY, **{KEY: None})), {"account_field_is_text": False}),
    "empty": (dict(body=dict(GOOD_BODY, **{KEY: ""})), {"account_field_is_text": False}),
    "none current": (dict(listed_accounts=accounts(False, False)),
                     {"accounts_in_the_list": 2, "accounts_shown_as_current": 0,
                      "account_field_is_text": True, "accounts_with_the_same_text": 1,
                      "current_account_has_the_same_text": False}),
    "two current": (dict(listed_accounts=accounts(True, True)),
                    {"accounts_shown_as_current": 2, "accounts_with_the_same_text": 1,
                     "current_account_has_the_same_text": False}),
    "current as words": (dict(listed_accounts=accounts("true", False)),
                         {"accounts_shown_as_current": 0}),
    "current lacks the field": (dict(listed_accounts=[
        {k: v for k, v in sb.ACCOUNTS[0].items() if k != KEY}, dict(sb.ACCOUNTS[1])]),
        {"accounts_shown_as_current": 1, "accounts_with_that_field": 1,
         "current_account_has_that_field": False, "accounts_with_the_same_text": 0}),
    "current has another": (dict(listed_accounts=accounts(a0={KEY: "K-OTHER-7777"})),
                            {"accounts_shown_as_current": 1, "current_account_has_that_field": True,
                             "current_account_has_the_same_text": False,
                             "accounts_with_the_same_text": 0}),
}


@pytest.mark.parametrize("way", sorted(WAYS))
def test_each_way_the_account_cannot_be_read_says_which_in_counts(way):
    given, expected = WAYS[way]
    e = stopped(bank(**given))
    assert e.reason == "the list gives its account in a form this cannot read"
    for k, v in expected.items():
        assert e.facts[k] == v, (k, e.facts)
    assert all(isinstance(v, (int, bool)) for v in e.facts.values()), e.facts
    # Kept whole by the word list, keys, values and the reason alike.
    assert shape_tree(e.facts) == e.facts
    assert all(shape_tree(k) == k for k in e.facts)
    assert _step(e.reason) == e.reason and shape_tree(e.reason) == e.reason
    text = json.dumps(e.facts) + str(e)
    for value in SECRETS:
        assert value not in text, value


def test_the_ways_are_told_apart():
    facts = {way: stopped(bank(**given)).facts for way, (given, _) in WAYS.items()}
    assert facts["no other field"] != facts["two other fields"]
    assert facts["a number"] != facts["current has another"]
    assert facts["none current"] != facts["two current"]
    assert facts["current lacks the field"] != facts["current has another"]


@pytest.mark.parametrize("body,answer", [
    (None, None), ("str", {}), ([], {"accountList": "abc"}), (7, {"accountList": {"k": 1}}),
    (GOOD_BODY, None), (GOOD_BODY, {"accountList": None}),
    (GOOD_BODY, {"accountList": ["K-ALPHA-0001", 5, None, dict(sb.ACCOUNTS[0])]}),
    ({"a": 1, "b": 2}, {"accountList": [None, {"a": 1}]}),
])
def test_the_facts_never_raise_on_what_a_page_could_send(body, answer):
    facts = site.account_key_facts(body, answer)
    assert isinstance(facts, dict) and shape_tree(facts) == facts


@pytest.mark.parametrize("body,answer,key", [
    (GOOD_BODY, sb.answer([]), KEY),
    (dict(GOOD_BODY, **{KEY: " K-ALPHA-0001"}), sb.answer([]), ""),
    (GOOD_BODY, sb.answer([], accounts("true")), ""),
    (GOOD_BODY, sb.answer([], accounts(False, True)), ""),
    (dict(GOOD_BODY, zqxHandle="x"), sb.answer([]), ""),
    ({"docCategoryId": "C", "year": "2026", "lang": "en"}, sb.answer([]), ""),
    ("body", sb.answer([]), ""),
])
def test_which_account_name_is_read_is_unchanged(body, answer, key):
    assert site.account_key_of(body, answer) == key


def _config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "document_types": ["Statement"], "default_start_date": "", "min_pdf_bytes": 2000,
        "max_path_length": 240, "delay_min_seconds": 0, "delay_max_seconds": 0,
        "pilot_count": 5}), encoding="utf-8")
    return cfg


def _attach(monkeypatch, page):
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "browser", lambda self: None)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    monkeypatch.setattr(app_mod.tabs, "on_its_site", lambda app, *a, **k: page)


def test_a_run_stops_with_the_facts_in_its_failure_file(tmp_path, monkeypatch, capsys):
    page = bank(**WAYS["two other fields"][0])
    _attach(monkeypatch, page)
    try:
        code = app_mod.main(["--pilot", "--config", str(_config(tmp_path))])
    except SystemExit as e:
        code = ("exit", e.code)
    assert code == ("exit", 0)
    out = capsys.readouterr().out
    assert "did not answer the way this app knows" in " ".join(out.split())
    (written,) = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["step"] == "read the statements list"
    assert report["reason"] == "the list gives its account in a form this cannot read"
    said = report["extra"]["postmortem"]
    assert said["other_list_fields"] == 2 and said["other_fields_also_in_an_account"] == 1
    text = written.read_text(encoding="utf-8")
    for value in SECRETS:
        assert value not in text and value not in out, value
    assert not page.pdfs
    assert not [a for a in page.asked if a[0] in sb.PRESSES or a[0] == "goto"], page.asked


def test_diagnose_says_the_same_facts(tmp_path, monkeypatch, capsys):
    page = bank(**WAYS["current has another"][0])
    _attach(monkeypatch, page)
    app_mod.main(["--diagnose", "--config", str(_config(tmp_path))])
    capsys.readouterr()
    written = (tmp_path / "out" / "Diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8")
    listed = json.loads(written)["survey"]["list"]
    # The stop's class name is masked by the word list, as at base.
    assert "stopped" in listed
    for k, v in WAYS["current has another"][1].items():
        assert listed[k] == v, k
    for value in SECRETS:
        assert value not in written, value
