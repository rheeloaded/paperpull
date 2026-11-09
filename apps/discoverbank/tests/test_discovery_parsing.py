import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock

_repo_root = Path(__file__).resolve().parents[3]
_app_dir = Path(__file__).resolve().parents[1]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from apps.discoverbank.discoverbank_site import (
    discoverbank_download,
    parse_statements_api,
    RawDoc,
    _write_if_pdf,
)


def test_parse_statements_api():
    sample_json = [
        {
            "name": "October 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-12345",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-12345",
                }
            ],
        },
        {
            "name": "September 2026",
            "statementDate": "2026-09-30T00:00:00-05:00",
            "id": "stmt-67890",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-67890",
                }
            ],
        },
    ]

    docs = parse_statements_api(sample_json, "Checking (••••)")
    assert len(docs) == 2
    assert docs[0].title == "Checking Statement"
    assert docs[0].date_text == "2026-10-31"
    assert "stmt-12345" in docs[0].href
    assert docs[0].account == "Checking (••••)"
    assert docs[0].text == "October 2026"
    assert docs[0].row_index == 0
    assert docs[1].date_text == "2026-09-30"
    assert docs[1].row_index == 1


def test_parse_statements_api_savings():
    sample_json = [
        {
            "name": "October 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-99999",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC2/statements/stmt-99999",
                }
            ],
        }
    ]
    docs = parse_statements_api(sample_json, "Online Savings Account (••••)")
    assert len(docs) == 1
    assert docs[0].title == "Savings Statement"
    assert docs[0].date_text == "2026-10-31"
    assert docs[0].account == "Online Savings Account (••••)"


def test_parse_statements_api_skips_missing_binary():
    sample_json = [
        {
            "name": "No binary",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-nobin",
            "links": [
                {
                    "rel": "self",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-nobin",
                }
            ],
        },
        {
            "name": "Valid binary",
            "statementDate": "2026-08-31T00:00:00-05:00",
            "id": "stmt-valid",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-valid",
                }
            ],
        },
    ]
    docs = parse_statements_api(sample_json, "Checking")
    assert len(docs) == 1
    assert docs[0].text == "Valid binary"
    assert docs[0].date_text == "2026-08-31"
    # The one with no PDF is a statement missed, so the list is not whole.
    assert docs.passed_over == ("statement list",)


def test_raw_doc_fields():
    doc = RawDoc(
        title="Checking Statement",
        date_text="2026-10-31",
        href="https://bank.discover.com/test",
        text="October 2026",
        account="Checking (••••)",
        row_index=0,
    )
    assert doc.title == "Checking Statement"
    assert doc.date_text == "2026-10-31"
    assert doc.href == "https://bank.discover.com/test"
    assert doc.text == "October 2026"
    assert doc.account == "Checking (••••)"
    assert doc.row_index == 0


def test_parse_statements_api_money_market_and_cd():
    sample_json = [
        {
            "name": "MM Oct 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-mm",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC3/statements/stmt-mm"}],
        },
        {
            "name": "CD Oct 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-cd",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC4/statements/stmt-cd"}],
        },
    ]
    mm_docs = parse_statements_api([sample_json[0]], "Money Market Account (••••1111)")
    assert len(mm_docs) == 1
    assert mm_docs[0].title == "Money Market Statement"

    cd_docs = parse_statements_api([sample_json[1]], "12-Month CD (••••2222)")
    assert len(cd_docs) == 1
    assert cd_docs[0].title == "CD Statement"


def test_parse_statements_api_null_date_and_unsafe_url():
    """None of these can be filed. No date, a card site's address, a plain
    http one and a day that does not exist. Each is refused and the list is
    not whole."""
    sample_json = [
        {
            "name": "Null date",
            "statementDate": None,
            "id": "stmt-null",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-null"}],
        },
        {
            "name": "Unsafe URL",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-unsafe",
            "links": [{"rel": "binary", "href": "https://card.discover.com/forbidden.pdf"}],
        },
        {
            "name": "HTTP URL",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-http",
            "links": [{"rel": "binary", "href": "http://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-http"}],
        },
        {
            "name": "Not a day",
            "statementDate": "2026-02-30T00:00:00-05:00",
            "id": "stmt-feb30",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-feb30"}],
        },
    ]
    docs = parse_statements_api(sample_json, "Checking")
    assert list(docs) == []
    assert docs.passed_over == ("statement list",)


def test_a_statement_is_kept_only_under_the_account_it_was_listed_for():
    """Both accounts are checking, and neither id carries a product code,
    so only the account its PDF sits under tells them apart."""
    sample_json = [
        {"name": "Ours", "statementDate": "2026-10-31", "id": "a",
         "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/a"}]},
        {"name": "Theirs", "statementDate": "2026-10-31", "id": "b",
         "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC9/statements/b"}]},
    ]
    docs = parse_statements_api(sample_json, "Checking (••••0001)", "ACC1")
    assert [d.text for d in docs] == ["Ours"]
    assert docs.passed_over == ("statement list",)


def test_the_kind_comes_from_the_name_and_the_id_and_they_must_agree():
    def one(label, account_id):
        return parse_statements_api([
            {"name": "x", "statementDate": "2026-10-31", "id": "s",
             "links": [{"rel": "binary", "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/%s/statements/s" % account_id}]}], label, account_id)

    # The name alone, the id alone, and both saying one thing.
    assert one("Checking (••••0001)", "ACC1")[0].title == "Checking Statement"
    assert one("Rainy day fund (••••0002)", "9~OSA~9")[0].title == "Savings Statement"
    assert one("Rainy day fund (••••0002)", "9~OSA~9")[0].account == \
        "Rainy day fund (••••0002)"
    assert one("Online Savings (••••0002)", "9~OSA~9")[0].title == "Savings Statement"
    # Neither says, so it is a statement of the account it was listed for.
    assert one("Rainy day fund (••••0002)", "ACC2")[0].title == "Statement"
    # They disagree, so it is refused rather than filed as either.
    got = one("Checking (••••0001)", "9~OSA~9")
    assert list(got) == [] and got.passed_over == ("statement list",)
    # An account id that only looks like a product code somewhere is no code.
    assert one("Savings (••••0002)", "stmt-oc")[0].title == "Savings Statement"


def test_an_answer_that_is_not_a_list_is_not_whole():
    for answer in ({"statements": []}, None, "error"):
        got = parse_statements_api(answer, "Checking")
        assert list(got) == [] and got.passed_over == ("statement list",)


def test_discoverbank_download_success(tmp_path):
    page = MagicMock()
    valid_pdf = b"%PDF-1.4 test content\n%%EOF"
    b64 = base64.b64encode(valid_pdf).decode("ascii")
    page.evaluate.return_value = {"ok": True, "b64": b64}

    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-1",
    )
    assert res is True
    assert out_file.exists()
    assert out_file.read_bytes() == valid_pdf


def test_discoverbank_download_invalid_pdf(tmp_path):
    page = MagicMock()
    not_pdf = b"<html>Sign In Required</html>"
    b64 = base64.b64encode(not_pdf).decode("ascii")
    page.evaluate.return_value = {"ok": True, "b64": b64}

    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-1",
    )
    assert res is False
    assert not out_file.exists()


def test_discoverbank_download_unsafe_url(tmp_path):
    page = MagicMock()
    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="https://card.discover.com/download/pdf",
    )
    assert res is False
    assert not out_file.exists()
    page.evaluate.assert_not_called()


def test_discoverbank_download_refuses_an_address_that_is_no_statement(tmp_path):
    page = MagicMock()
    out_file = tmp_path / "statement.pdf"
    for href in ("https://bank.discover.com/download/pdf",
                 "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements",
                 "https://www.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/s"):
        assert discoverbank_download(page, None, "Checking", "2026-10-31", out_file,
                                     href=href) is False
    page.evaluate.assert_not_called()
    assert not out_file.exists()


def test_discoverbank_download_empty_href(tmp_path):
    page = MagicMock()
    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="",
    )
    assert res is False
    assert not out_file.exists()


def test_parse_statements_api_relative_url():
    sample_json = [
        {
            "name": "August 2026",
            "statementDate": "2026-08-31T00:00:00-05:00",
            "id": "stmt-relative",
            "links": [
                {
                    "rel": "binary",
                    "href": "/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-relative",
                }
            ],
        }
    ]
    docs = parse_statements_api(sample_json, "Savings (••••)")
    assert len(docs) == 1
    assert docs[0].href == "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-relative"


def test_discoverbank_download_relative_url(tmp_path):
    page = MagicMock()
    valid_pdf = b"%PDF-1.4 relative test\n%%EOF"
    b64 = base64.b64encode(valid_pdf).decode("ascii")
    page.evaluate.return_value = {"ok": True, "b64": b64}

    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-08-31", out_file,
        href="/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-relative",
    )
    assert res is True
    assert out_file.exists()
    assert out_file.read_bytes() == valid_pdf


def test_write_if_pdf_atomic(tmp_path):
    out_file = tmp_path / "test.pdf"
    assert not _write_if_pdf(b"not a pdf", out_file)
    assert not out_file.exists()

    valid_pdf = b"%PDF-1.7 atomic write content"
    assert _write_if_pdf(valid_pdf, out_file)
    assert out_file.exists()
    assert out_file.read_bytes() == valid_pdf


def test_list_deposit_accounts_from_fiber():
    from discoverbank_site import list_deposit_accounts
    page = MagicMock()
    page.evaluate.return_value = [[
        {"label": "Checking (••••)", "id": "SM_CHECKING"},
        {"label": "Savings (••••)", "id": "SM_SAVINGS"},
    ]]
    accounts = list_deposit_accounts(page)
    assert len(accounts) == 2
    assert accounts[0]["text"] == "Checking (••••)"
    assert accounts[1]["text"] == "Savings (••••)"
    # Read from the page's state, never by opening the menu.
    page.locator.assert_not_called()
    page.click.assert_not_called()


def _menu_and_lists(menus, lists, failing=()):
    def mock_eval(script, *args):
        if "__reactFiber" in script:
            return menus
        if "fetch(url" in script:
            url = args[0]
            for acct_id, items in lists.items():
                if url.endswith("/accounts/%s/statements" % acct_id):
                    if acct_id in failing:
                        return {"ok": False, "status": 500, "data": None}
                    return {"ok": True, "status": 200, "data": items}
            return {"ok": False, "status": 404, "data": None}
        if "performance" in script:
            return []
        raise AssertionError("an unexpected script: " + script[:80])
    return mock_eval


def _item(acct_id, sid):
    return {"statementDate": "2026-10-31", "name": sid,
            "links": [{"rel": "binary",
                       "href": "/bank/deposits/servicing/documents/v1/accounts/%s/statements/%s"
                               % (acct_id, sid)}]}


def test_discoverbank_collect_fiber_direct_fetch():
    from discoverbank_site import discoverbank_collect
    page = MagicMock()
    page.evaluate.side_effect = _menu_and_lists(
        [[{"label": "Checking (••••)", "id": "SM_CHECKING"},
          {"label": "Savings (••••)", "id": "SM_SAVINGS"}]],
        {"SM_CHECKING": [_item("SM_CHECKING", "stmt-oc")],
         "SM_SAVINGS": [_item("SM_SAVINGS", "stmt-osa")]})
    docs = discoverbank_collect(page)
    assert len(docs) == 2 and docs.passed_over == ()
    accts = {d.account for d in docs}
    assert "Checking (••••)" in accts
    assert "Savings (••••)" in accts
    page.locator.assert_not_called()


def test_an_account_whose_list_fails_leaves_the_list_not_whole():
    """The list call used to answer [] for an error, so a savings account
    whose list failed read as one with no statements and the list was
    whole without it."""
    from discoverbank_site import discoverbank_collect
    page = MagicMock()
    page.evaluate.side_effect = _menu_and_lists(
        [[{"label": "Checking (••••)", "id": "SM_CHECKING"},
          {"label": "Savings (••••)", "id": "SM_SAVINGS"}]],
        {"SM_CHECKING": [_item("SM_CHECKING", "a")], "SM_SAVINGS": [_item("SM_SAVINGS", "b")]},
        failing={"SM_SAVINGS"})
    docs = discoverbank_collect(page)
    assert [d.text for d in docs] == ["a"]
    assert docs.passed_over == ("statement list",)


def test_an_account_id_that_is_not_one_is_never_put_in_a_path():
    from discoverbank_site import discoverbank_collect
    page = MagicMock()
    asked = []

    def mock_eval(script, *args):
        if "__reactFiber" in script:
            return [[{"label": "Checking (••••)", "id": "../../transfers?x=1"}]]
        asked.append(args)
        return {"ok": True, "status": 200, "data": []}
    page.evaluate.side_effect = mock_eval
    docs = discoverbank_collect(page)
    assert list(docs) == [] and docs.passed_over == ("account menu",)
    assert asked == []


def test_two_menus_with_different_accounts_are_no_list():
    from discoverbank_site import discoverbank_collect
    page = MagicMock()
    page.evaluate.side_effect = _menu_and_lists(
        [[{"label": "Checking (••••)", "id": "A"}],
         [{"label": "Savings (••••)", "id": "B"}]], {})
    assert discoverbank_collect(page) is None


def test_what_each_menu_option_is():
    from discoverbank_site import ACCOUNT, OTHER, REFUSED, option_is
    for label, account_id, want in [
        ("Checking (••••0001)", "1~OC~1", ACCOUNT),
        ("Rainy day fund (••••0002)", "R2", ACCOUNT),
        ("Certificate of Deposit (••••0003)", "3~CD~3", ACCOUNT),
        ("All accounts", "", OTHER),
        ("Open a new account", "", OTHER),
        ("Credit Card (••••0004)", "C4", OTHER),
        ("Personal Loans", "L5", OTHER),
        ("Savings (••••0006)", "", REFUSED),
        ("Transfer funds", "T7", REFUSED),
        ("Open a savings account", "S8", REFUSED),
    ]:
        assert option_is({"label": label, "id": account_id}) == want, label


def test_an_option_that_may_be_an_account_and_is_not_read_is_passed_over():
    from discoverbank_site import discoverbank_collect, list_deposit_accounts
    page = MagicMock()
    page.evaluate.side_effect = _menu_and_lists(
        [[{"label": "Checking (••••)", "id": "SM_CHECKING"},
          {"label": "Transfer funds", "id": "T1"},
          {"label": "All accounts", "id": ""}]],
        {"SM_CHECKING": [_item("SM_CHECKING", "a")]})
    docs = discoverbank_collect(page)
    assert [d.text for d in docs] == ["a"]
    assert docs.passed_over == ("account menu",)
    assert [a["text"] for a in list_deposit_accounts(page)] == ["Checking (••••)"]


def test_a_menu_that_names_no_account_is_no_menu():
    """A dropdown of years or of document kinds is not the account menu."""
    from discoverbank_site import read_account_menu
    page = MagicMock()
    page.evaluate.return_value = [[{"label": "2026", "id": "2026"},
                                   {"label": "2025", "id": "2025"}]]
    assert read_account_menu(page) is None
