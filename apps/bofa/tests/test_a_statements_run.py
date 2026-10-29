"""A Bank of America run through its own main, on a stand-in statements page
(standin_bank). Discover lists every account's statements, Pilot files a
statement only when its text names its own day and account better than any
it could be taken for, and everything else is kept in Manual Review or not
kept at all. Login says a session is signed in only when the list answered.
The one press is the Statements heading, when the page leaves it shut, and
paperpull_core.pressing.click is the stand-in's own here (standin_bank.press).
Every value is invented."""
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
from paperpull_core import delivery, pressing, testkit
from paperpull_core.run_reporting import PREFIX

INVENTED = ("K-ALPHA-0001", "K-BRAVO-0002", "DOC000000000101", "TOKEN-T", "STANDINTOKEN",
            "lookupDocuments", "getpdf")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    site.forget()
    monkeypatch.setattr(pressing, "click", sb.press)
    yield
    site.forget()


def _config(tmp_path, **more):
    cfg = tmp_path / "config.json"
    data = {"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "document_types": ["Statement", "Tax Document"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5}
    data.update(more)
    cfg.write_text(json.dumps(data), encoding="utf-8")
    return cfg


def statement_pdf(row, account=None, day=None):
    """A statement that names its own day and account, or the ones given."""
    when = day or row.get("date") or "2000-01-01"
    y, m, d = when.split("-")
    month = ("January February March April May June July August September October "
             "November December").split()[int(m) - 1]
    return testkit.text_pdf(["Bank of America", account or row.get("accountDisplayName", ""),
                             "Statement for the period ending %s %d, %s" % (month, int(d), y),
                             "Page 1 of 4"])


@pytest.fixture
def bank(monkeypatch):
    page = sb.Bank()
    page.pdf_maker = statement_pdf
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "browser", lambda self: None)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    monkeypatch.setattr(app_mod.tabs, "on_its_site", lambda app, *a, **k: page)
    return page


def run(tmp_path, *args, **config):
    cfg = _config(tmp_path, **config)
    try:
        code = app_mod.main([*args, "--config", str(cfg)])
    except SystemExit as e:
        code = ("exit", e.code)
    return code


def result(out):
    lines = [line for line in out.splitlines() if line.startswith(PREFIX)]
    payload = lines[-1][len(PREFIX):]
    return json.loads(payload if payload.startswith("{") else payload.split(" ", 1)[1])


def records(tmp_path, name="progress.json"):
    path = tmp_path / "out" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def no_presses(page):
    assert not [a for a in page.asked if a[0] in sb.PRESSES or a[0] == "goto"], page.asked


# -- Discover ------------------------------------------------------------------

def test_discover_lists_every_accounts_statements(tmp_path, bank, capsys):
    assert run(tmp_path, "--discover") == 0
    out = capsys.readouterr().out
    known = records(tmp_path, "discovery.json")
    assert sorted((r["account"], r["date"]) for r in known.values()) == [
        ("Everyday Checking", "2025-12-15"), ("Everyday Checking", "2026-01-15"),
        ("Everyday Checking", "2026-02-15"), ("Travel Card", "2026-01-15")]
    assert all(r["document_id"] and r["account_ref"] and r["year"] for r in known.values())
    assert result(out)["stopped"] == 0
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note["complete"] is True
    no_presses(bank)


def test_two_accounts_of_one_name_keep_their_statements_of_one_day(tmp_path, bank, monkeypatch):
    twin = dict(sb.ACCOUNTS[1], accountDisplayName="Everyday Checking")
    monkeypatch.setattr(sb, "ACCOUNTS", [sb.ACCOUNTS[0], twin])
    bank.listed = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")], accounts=sb.ACCOUNTS)
    other = sb.row("DOC000000000201", twin, "2026-01-15")
    bank.answer_list = lambda body: ([other] if body[sb.KEY] == "K-BRAVO-0002" and body["year"] == "2026"
                                     else list(sb.STATEMENTS.get((body[sb.KEY], body["year"]), [])))
    assert run(tmp_path, "--discover") == 0
    known = records(tmp_path, "discovery.json")
    jan = sorted((r["occurrence"], r["account_ref"]) for r in known.values() if r["date"] == "2026-01-15")
    assert [o for o, _ in jan] == [0, 1] and {a for _, a in jan} == {"K-ALPHA-0001", "K-BRAVO-0002"}


def test_discover_off_the_statements_page_stops_and_says_where_to_go(tmp_path, bank, capsys):
    bank.url = "https://secure.bankofamerica.com/myaccounts/overview/?k=X"
    assert run(tmp_path, "--discover") == ("exit", 0)
    raw = capsys.readouterr().out
    assert "not on Statements & Documents" in " ".join(raw.split())
    assert result(raw)["stopped"] == 1
    assert bank.reloads == 0 and not bank.lists
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note["complete"] is False


def test_a_page_the_app_does_not_know_stops_with_a_failure_file_of_counts(tmp_path, bank, capsys):
    bank.first_body = {"unknown": "K-ALPHA-0001", "other": "x", "year": "2026"}
    assert run(tmp_path, "--pilot") == ("exit", 0)
    out = " ".join(capsys.readouterr().out.split())
    assert "did not answer the way this app knows" in out and "#121" in out
    files = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert len(files) == 1
    written = files[0].read_text(encoding="utf-8")
    for value in INVENTED + ("Everyday Checking", "Dana"):
        assert value not in written, value
    assert not bank.pdfs and not list((tmp_path / "out").rglob("*.pdf"))


def test_with_no_browser_open_discover_says_to_sign_in_first(tmp_path, monkeypatch, capsys):
    def gone(self):
        raise SystemExit("Could not connect to your signed-in browser.\nRun login.bat first.")
    monkeypatch.setattr(app_mod.App, "browser", gone)
    monkeypatch.setattr(site, "collect_documents", lambda *a, **k: pytest.fail("the list was asked for"))
    code = run(tmp_path, "--discover")
    assert code[0] == "exit" and "Run login.bat first" in str(code[1])


# -- Pilot and the identity check ------------------------------------------------

def test_pilot_files_each_statement_that_names_its_own_day_and_account(tmp_path, bank, capsys):
    assert run(tmp_path, "--pilot") == 0
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf"))
    assert saved == ["2025-12-15 Bank of America Statement - Everyday Checking.pdf",
                     "2026-01-15 Bank of America Statement - Everyday Checking.pdf",
                     "2026-01-15 Bank of America Statement - Travel Card.pdf",
                     "2026-02-15 Bank of America Statement - Everyday Checking.pdf"]
    done = records(tmp_path)
    assert len(done) == 4 and all(r["downloaded_ok"] for r in done.values())
    assert result(capsys.readouterr().out)["new_files"] == 4
    assert sorted(bank.pdfs) == sorted(sb.LINK_BASE + d for d in (
        "DOC000000000091", "DOC000000000101", "DOC000000000102", "DOC000000000201"))
    no_presses(bank)


def test_pilot_on_a_page_whose_reload_shuts_the_statements_heading_files_its_statements(
        tmp_path, bank, capsys):
    """appchamp's first real run (#121, 2026-10-26). Discover listed every
    statement, then Pilot and Resume each stopped on the first one because
    the reload left the Statements heading shut and no Download PDF link was
    drawn. The heading is opened once, the way both recordings opened it."""
    bank.heading = bank.heading_on_reload = "shut"
    assert run(tmp_path, "--pilot", "--max-docs", "1") == 0
    saved = [p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf")]
    assert saved == ["2026-02-15 Bank of America Statement - Everyday Checking.pdf"]
    assert [a for a in bank.asked if a[0] in sb.PRESSES] == [("click", "the Statements heading")]
    assert not [a for a in bank.asked if a[0] == "goto"]
    # Discover listed without it, and the download heard the page again.
    assert bank.reloads == 2


def test_pilot_on_a_page_whose_links_open_by_a_script_files_every_statement(tmp_path, bank, capsys):
    """appchamp's second real run (#121, 2026-10-27). The one link drawn had
    "#" for its address. One link is pressed, once, and every statement is
    asked with its own row's call, the PDF the press brought kept nowhere."""
    bank.links = sb.script_links(bank.listed["documentList"])
    bank.press_downloads = lambda row: ["blob:https://secure.bankofamerica.com/0f0e-sample"]
    assert run(tmp_path, "--pilot") == 0
    saved = sorted(p.name for p in (tmp_path / "out").rglob("*.pdf"))
    assert saved == ["2025-12-15 Bank of America Statement - Everyday Checking.pdf",
                     "2026-01-15 Bank of America Statement - Everyday Checking.pdf",
                     "2026-01-15 Bank of America Statement - Travel Card.pdf",
                     "2026-02-15 Bank of America Statement - Everyday Checking.pdf"]
    assert result(capsys.readouterr().out)["new_files"] == 4
    assert [a for a in bank.asked if a[0] in sb.PRESSES] == [
        ("click", "a statement's Download PDF link")]
    # Once again for the statement pressed, then once for each statement.
    asked = [json.loads(c["body"])["docId"] for c in bank.pdf_calls]
    assert asked[0] == "DOC000000000101" and sorted(asked[1:]) == [
        "DOC000000000091", "DOC000000000101", "DOC000000000102", "DOC000000000201"]
    assert ("delete", "blob:https://secure.bankofamerica.com/0f0e-sample") in bank.downloads_ended
    assert not bank.pdfs and not list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


def test_pilot_at_the_second_address_files_every_statement(tmp_path, bank, capsys):
    """crazyhorse90210's run (#121, 2026-10-28) stopped on "The Bank of
    America tab is not on Statements & Documents" with the window on it, at
    /statements-documents/home/. The same page there files its statements,
    by the press its links need when they open by a script."""
    bank.url = sb.SECOND_PAGE_URL
    bank.links = sb.script_links(bank.listed["documentList"])
    assert run(tmp_path, "--pilot") == 0
    saved = sorted(p.name for p in (tmp_path / "out").rglob("*.pdf"))
    assert saved == ["2025-12-15 Bank of America Statement - Everyday Checking.pdf",
                     "2026-01-15 Bank of America Statement - Everyday Checking.pdf",
                     "2026-01-15 Bank of America Statement - Travel Card.pdf",
                     "2026-02-15 Bank of America Statement - Everyday Checking.pdf"]
    out = capsys.readouterr().out
    assert result(out)["new_files"] == 4 and "not on Statements & Documents" not in out
    assert bank.url == sb.SECOND_PAGE_URL


def test_something_over_a_download_pdf_link_stops_the_run(tmp_path, bank, capsys, monkeypatch):
    bank.links = sb.script_links(bank.listed["documentList"])

    def covered(page, el, *, css, what, words, step="press a control", **k):
        raise pressing.Covered(step, "something on the page is over the control",
                               ["Something on the page covers %s, so nothing was pressed." % what,
                                pressing.AGAIN], {"verdict": "covered"})
    monkeypatch.setattr(pressing, "click", covered)
    assert run(tmp_path, "--pilot") == ("exit", 0)
    raw = capsys.readouterr().out
    assert "covers a statement's Download PDF link, so nothing was pressed" in " ".join(raw.split())
    (written,) = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["step"] == "download a statement" and report["extra"]["verdict"] == "covered"
    assert result(raw)["stopped"] == 1
    assert not bank.pdf_calls and not list((tmp_path / "out").rglob("*.pdf"))


def test_discover_and_login_on_a_shut_heading_press_nothing(tmp_path, bank, capsys):
    """A list needs no PDF link. appchamp's Discover listed every statement
    with the heading shut, and still does, pressing nothing."""
    bank.heading = bank.heading_on_reload = "shut"
    assert run(tmp_path, "--discover") == 0
    raw = capsys.readouterr().out
    assert result(raw)["stopped"] == 0 and len(records(tmp_path, "discovery.json")) == 4
    assert run(tmp_path, "--login") in (0, None)
    assert "Success: the statements list answered, with 2 account(s)." in capsys.readouterr().out
    no_presses(bank)


def test_a_page_whose_links_hide_their_address_stops_with_its_counts(tmp_path, bank, capsys):
    """What the failure file says when no form can be learned, so the next
    round knows why. Counts and fixed words only, never an address."""
    bank.heading = bank.heading_on_reload = "shut"
    bank.opened = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")])
    bank.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": "javascript:void(0)", "raw": "javascript:void(0)",
                   "data": ["DOC000000000101"]}]
    # Its press asks for something that is no PDF.
    bank.press_calls = lambda row: [dict(sb.json_call(row)[0], answer="application/json")]
    assert run(tmp_path, "--pilot", "--max-docs", "1") == ("exit", 0)
    out = " ".join(capsys.readouterr().out.split())
    assert "brought no PDF this app could hear" in out and "#121" in out
    (written,) = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["step"] == "download a statement"
    assert report["reason"] == "no pdf url after the link was pressed"
    said = report["extra"]["postmortem"]
    assert said["statements_heading"] == "opened" and said["pdf_links"] == 1
    assert said["links_to_no_page"] == 1 and said["links_with_an_id_elsewhere"] == 1
    assert said["links_with_an_id"] == 0 and said["times_the_list_was_read"] == 2
    assert (said["pdf_link"], said["urls_read_after_the_link_was_pressed"], said["pdf_files_read"],
            said["pdf_urls"]) == ("pressed", 1, 0, 0)
    text = written.read_text(encoding="utf-8")
    for value in INVENTED + ("Everyday Checking", "Dana", "javascript"):
        assert value not in text, value
    assert not bank.pdfs and not list((tmp_path / "out").rglob("*.pdf"))


def test_something_over_the_statements_heading_stops_the_run(tmp_path, bank, capsys, monkeypatch):
    """A press the core will not make, a chat bubble over the heading say,
    stops the run with the stop said and a failure file of its facts."""
    bank.heading = bank.heading_on_reload = "shut"

    def covered(page, el, *, css, what, words, step="press a control", **k):
        raise pressing.Covered(step, "something on the page is over the control",
                               ["Something on the page covers %s, so nothing was pressed." % what,
                                pressing.AGAIN], {"verdict": "covered"})
    monkeypatch.setattr(pressing, "click", covered)
    assert run(tmp_path, "--pilot") == ("exit", 0)
    raw = capsys.readouterr().out
    assert "covers the Statements heading, so nothing was pressed" in " ".join(raw.split())
    (written,) = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["step"] == "expand the statements heading"
    assert report["extra"]["verdict"] == "covered"
    assert result(raw)["stopped"] == 1
    assert not bank.pdfs and not list((tmp_path / "out").rglob("*.pdf"))


JANUARY_CHECKING = "2026-01-15 Bank of America Statement - Everyday Checking.pdf"


def names_the_card_for_januarys_checking(row):
    """The checking account's January statement naming the card, which has
    a statement of the same day. Every other statement is its own."""
    if row.get("docId") == "DOC000000000101":
        return statement_pdf(row, account="Travel Card")
    return statement_pdf(row)


def test_pilot_with_max_docs_takes_only_that_many(tmp_path, bank, capsys):
    assert run(tmp_path, "--pilot", "--max-docs", "1") == 0
    saved = [p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf")]
    assert saved == ["2026-02-15 Bank of America Statement - Everyday Checking.pdf"]
    assert len(bank.pdfs) == 1


def test_a_statement_naming_another_accounts_is_kept_for_review_not_filed(tmp_path, bank, capsys):
    bank.pdf_maker = names_the_card_for_januarys_checking
    run(tmp_path, "--pilot")
    filed = {p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf")}
    assert JANUARY_CHECKING not in filed and len(filed) == 3
    review = [p.name for p in (tmp_path / "out" / "Manual Review").glob("*.pdf")]
    assert review == [JANUARY_CHECKING], review
    got = result(capsys.readouterr().out)
    assert got["wrong_document"] == 1 and got["manual_review"] == 1
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


def test_with_refuse_wrong_documents_set_a_wrong_statement_is_not_kept(tmp_path, bank, capsys):
    bank.pdf_maker = names_the_card_for_januarys_checking
    run(tmp_path, "--pilot", refuse_wrong_documents=True)
    assert JANUARY_CHECKING not in {p.name for p in (tmp_path / "out").rglob("*.pdf")}
    assert result(capsys.readouterr().out)["wrong_document"] == 1


def test_a_statement_sharing_its_day_with_another_account_is_still_checked_by_its_day(
        tmp_path, bank, capsys):
    """January's checking statement shares its day with the card's, so the
    check against that one tells them apart by account alone. It comes back
    as December's checking statement, which names the right account, and
    only the check against its own account's either side refuses it."""
    bank.pdf_maker = lambda row: (statement_pdf(row, day="2025-12-15")
                                  if row.get("docId") == "DOC000000000101" else statement_pdf(row))
    run(tmp_path, "--pilot")
    filed = {p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf")}
    assert JANUARY_CHECKING not in filed and len(filed) == 3
    assert [p.name for p in (tmp_path / "out" / "Manual Review").glob("*.pdf")] == [JANUARY_CHECKING]
    assert result(capsys.readouterr().out)["wrong_document"] == 1


def test_with_refuse_wrong_documents_set_another_months_statement_is_not_kept(tmp_path, bank, capsys):
    bank.pdf_maker = lambda row: statement_pdf(row, day="2026-01-15" if row.get("date") == "2026-02-15" else None)
    run(tmp_path, "--pilot", refuse_wrong_documents=True)
    names = {p.name for p in (tmp_path / "out").rglob("*.pdf")}
    assert "2026-02-15 Bank of America Statement - Everyday Checking.pdf" not in names
    assert result(capsys.readouterr().out)["wrong_document"] == 1


def test_a_file_the_bank_names_for_another_day_is_never_filed(tmp_path, bank, capsys):
    bank.pdf_disposition = 'attachment; filename="eStmt_2024-11-30.pdf"'
    run(tmp_path, "--pilot")
    assert not list((tmp_path / "out" / "Statements").glob("*.pdf"))
    assert len(list((tmp_path / "out" / "Manual Review").glob("*.pdf"))) == 4
    got = result(capsys.readouterr().out)
    assert got["wrong_document"] == 4 and got["new_files"] == 0


def test_with_refuse_wrong_documents_set_a_file_named_for_another_day_is_not_kept(tmp_path, bank, capsys):
    bank.pdf_disposition = 'attachment; filename="eStmt_2024-11-30.pdf"'
    run(tmp_path, "--pilot", refuse_wrong_documents=True)
    assert not list((tmp_path / "out").rglob("*.pdf"))
    assert result(capsys.readouterr().out)["wrong_document"] == 4


def test_a_statement_alone_in_its_account_is_still_checked_by_its_day(tmp_path, bank, capsys):
    """The card has one statement, so it has nothing either side, and its
    day is checked all the same. It comes back as another month's, with no
    day in its file name."""
    bank.pdf_disposition = "inline"
    bank.pdf_maker = lambda row: (statement_pdf(row, day="2025-11-20")
                                  if row.get("docId") == "DOC000000000201" else statement_pdf(row))
    run(tmp_path, "--pilot")
    filed = {p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf")}
    assert "2026-01-15 Bank of America Statement - Travel Card.pdf" not in filed and len(filed) == 3
    assert result(capsys.readouterr().out)["wrong_document"] == 1


def test_a_statement_the_page_could_not_ask_for_stops_the_run(tmp_path, bank, capsys):
    bank.pdf_raises = RuntimeError("TypeError: Failed to fetch")
    assert run(tmp_path, "--pilot") == ("exit", 0)
    got = result(capsys.readouterr().out)
    assert got["stopped"] == 1 and got["failed"] == 0 and len(bank.pdfs) == 1


def test_a_statement_whose_text_cannot_be_checked_is_kept_for_review(tmp_path, bank, capsys):
    bank.pdf_maker = lambda row: testkit.sample_pdf()
    run(tmp_path, "--pilot")
    assert not list((tmp_path / "out" / "Statements").glob("*.pdf"))
    assert len(list((tmp_path / "out" / "Manual Review").glob("*.pdf"))) == 4
    assert result(capsys.readouterr().out)["new_files"] == 0


def test_a_run_hands_the_bytes_to_place_with_their_identity_and_rivals(tmp_path, bank, monkeypatch):
    """January's two statements share a day, so each is handed to place
    with the other as what it could be taken for."""
    spy = testkit.StrictDelivery().install(monkeypatch)
    run(tmp_path, "--pilot", "--start-date", "2026-01-01", "--end-date", "2026-01-31")
    places = [c for c in spy.calls if c.name == "place"]
    assert len(places) == 2
    for call in places:
        expect, rivals = call.arguments["expect"], call.arguments["rivals"]
        assert expect.date == "2026-01-15" and expect.label in ("Everyday Checking", "Travel Card")
        assert [r.label for r in rivals] == [{"Everyday Checking": "Travel Card",
                                               "Travel Card": "Everyday Checking"}[expect.label]]


def test_a_statement_naming_another_month_of_its_account_is_kept_for_review(tmp_path, bank, capsys):
    """February's statement comes back naming January's day."""
    bank.pdf_maker = lambda row: statement_pdf(row, day="2026-01-15" if row.get("date") == "2026-02-15" else None)
    run(tmp_path, "--pilot")
    filed = {p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf")}
    assert "2026-02-15 Bank of America Statement - Everyday Checking.pdf" not in filed
    assert "2026-01-15 Bank of America Statement - Everyday Checking.pdf" in filed
    assert result(capsys.readouterr().out)["wrong_document"] == 1


def test_a_statement_no_longer_listed_is_not_asked_for(tmp_path, bank, capsys):
    assert run(tmp_path, "--discover") == 0
    bank.answer_list = lambda body: []
    run(tmp_path, "--resume", "--yes")
    assert not bank.pdfs and not list((tmp_path / "out").rglob("*.pdf"))


def test_a_sign_in_part_way_stops_the_run(tmp_path, bank, capsys):
    bank.pdf_status = 401
    code = run(tmp_path, "--pilot")
    assert code == 2 or code == ("exit", 0)
    out = capsys.readouterr().out
    assert "session has expired" in out and result(out)["new_files"] == 0


def test_run_all_asks_for_yes_first(tmp_path, bank, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_a: "no")
    run(tmp_path, "--all")
    assert "Aborted" in capsys.readouterr().out and not bank.lists


# -- Login ---------------------------------------------------------------------

def _login(tmp_path, monkeypatch, page, own):
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    monkeypatch.setattr(app_mod.tabs, "is_own", lambda tab: own)
    app_mod.main(["--login", "--config", str(_config(tmp_path))])


def test_login_says_signed_in_only_when_the_list_answered(tmp_path, capsys, monkeypatch):
    page = sb.Bank()
    _login(tmp_path, monkeypatch, page, own=False)
    said = " ".join(capsys.readouterr().out.split())
    assert "Success: the statements list answered, with 2 account(s)" in said
    no_presses(page)


@pytest.mark.parametrize("page", [
    sb.Bank(url="https://secure.bankofamerica.com/myaccounts/overview/"),
    sb.Bank(url="https://www.bankofamerica.com/"),
])
def test_login_off_the_statements_page_claims_nothing(page, tmp_path, capsys, monkeypatch):
    _login(tmp_path, monkeypatch, page, own=False)
    said = " ".join(capsys.readouterr().out.split()).lower()
    assert "success" not in said and "cannot say whether you are signed in" in said
    assert page.reloads == 0
    no_presses(page)


def test_login_says_when_the_list_did_not_answer(tmp_path, capsys, monkeypatch):
    page = sb.Bank()
    page.first_url = "https://secure.bankofamerica.com/sample/other/zone/x/v1/y"
    _login(tmp_path, monkeypatch, page, own=False)
    said = " ".join(capsys.readouterr().out.split()).lower()
    assert "success" not in said and "did not answer" in said


def test_login_names_a_sign_in_form(tmp_path, capsys, monkeypatch):
    page = sb.Bank(url="https://www.bankofamerica.com/", password=1)
    _login(tmp_path, monkeypatch, page, own=False)
    assert "shows a sign-in form" in " ".join(capsys.readouterr().out.split())


def test_login_opens_the_home_page_only_in_a_tab_it_opened(tmp_path, capsys, monkeypatch):
    page = sb.Bank(url="about:blank", password=1)
    _login(tmp_path, monkeypatch, page, own=True)
    assert [a for a in page.asked if a[0] == "goto"] == [("goto", "https://www.bankofamerica.com/")]


def test_login_never_moves_a_tab_of_the_persons(tmp_path, capsys, monkeypatch):
    page = sb.Bank(url="https://www.elsewhere.test/")
    _login(tmp_path, monkeypatch, page, own=False)
    assert not [a for a in page.asked if a[0] == "goto"]
    assert "no tab is on bankofamerica.com" in " ".join(capsys.readouterr().out.split())


def test_login_names_a_check(tmp_path, capsys, monkeypatch):
    page = sb.Bank(text="Enter the code we sent you")
    _login(tmp_path, monkeypatch, page, own=False)
    assert "Security challenge detected" in capsys.readouterr().out
    assert page.reloads == 0


# -- signed out, and Diagnose ----------------------------------------------------

def test_a_password_field_an_unreadable_page_or_the_sign_in_path_is_signed_out():
    assert site.looks_signed_out(sb.Bank(url="https://www.bankofamerica.com/", password=1))
    assert site.looks_signed_out(sb.Bank(url="https://secure.bankofamerica.com/login/sign-in/x.go"))
    assert site.looks_signed_out(sb.Bank(url=""))
    assert not site.looks_signed_out(sb.Bank(url="https://secure.bankofamerica.com/myaccounts/signin/x.go"))
    assert not site.looks_signed_out(sb.Bank())


def test_diagnose_writes_names_and_counts_and_never_the_owner_or_a_value(tmp_path, monkeypatch, capsys):
    cfg = _config(tmp_path, owner="Bill Grant")
    page = sb.Bank()
    page.title = lambda: "Bill Grant - Statements & Documents"
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    app_mod.main(["--diagnose", "--config", str(cfg)])
    written = (tmp_path / "out" / "Diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8")
    for value in INVENTED + ("Bill", "Grant"):
        assert value not in written, value
    info = json.loads(written)
    assert info["on_site"] is True and info["survey"]["list"]["accounts"] == 2
    assert "PDF links understood" in capsys.readouterr().out
    no_presses(page)


# -- which tab -----------------------------------------------------------------

OVERVIEW = "https://secure.bankofamerica.com/myaccounts/overview/?k=X"
ELSEWHERE = "https://mail.example/inbox"


class Browser:
    """The person's browser as page() reaches it, with these tabs open."""

    def __init__(self, *tabs):
        self.pages = list(tabs)

    def new_page(self):
        raise AssertionError("a tab of the run's own was opened")


def attached(monkeypatch, *tabs):
    ctx = Browser(*tabs)

    def browser(self):
        self._cdp_mode = True
        return ctx
    monkeypatch.setattr(app_mod.App, "browser", browser)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    return ctx


def an_app(tmp_path):
    cfg = _config(tmp_path)
    return app_mod.App(app_mod.build_parser().parse_args(["--discover", "--config", str(cfg)]))


def test_the_tab_on_statements_and_documents_is_the_one_worked_in(tmp_path, monkeypatch):
    """The first tab on the site used to be taken, so with the overview open
    before Statements & Documents a run worked in the overview."""
    overview, statements = sb.Bank(url=OVERVIEW), sb.Bank()
    attached(monkeypatch, sb.Bank(url=ELSEWHERE), overview, statements)
    assert an_app(tmp_path).page() is statements


def test_the_tab_at_the_second_address_is_the_one_worked_in(tmp_path, monkeypatch):
    """A second tester's Statements & Documents was at /statements-documents/home/,
    and 0.59.1 worked in another tab on the site, or stopped (#121)."""
    overview, statements = sb.Bank(url=OVERVIEW), sb.Bank(url=sb.SECOND_PAGE_URL)
    attached(monkeypatch, sb.Bank(url=ELSEWHERE), overview, statements)
    assert an_app(tmp_path).page() is statements


def test_a_tab_at_each_address_takes_neither(tmp_path, monkeypatch):
    attached(monkeypatch, sb.Bank(), sb.Bank(url=sb.SECOND_PAGE_URL))
    with pytest.raises(pressing.Stop) as stopped:
        an_app(tmp_path).page()
    assert stopped.value.facts == {"tabs_on_the_statements_page": 2}


def test_a_tab_on_the_site_is_still_taken_when_none_is_on_the_statements_page(tmp_path, monkeypatch):
    overview = sb.Bank(url=OVERVIEW)
    attached(monkeypatch, sb.Bank(url=ELSEWHERE), overview)
    assert an_app(tmp_path).page() is overview


def test_two_tabs_on_statements_and_documents_take_neither(tmp_path, monkeypatch):
    first, second = sb.Bank(), sb.Bank()
    attached(monkeypatch, first, second)
    app = an_app(tmp_path)
    with pytest.raises(pressing.Stop) as stopped:
        app.page()
    assert stopped.value.step == "get the statements tab"
    assert stopped.value.facts == {"tabs_on_the_statements_page": 2}
    assert app._work_page is None


def test_a_run_with_two_statements_tabs_stops_and_says_so(tmp_path, monkeypatch, capsys):
    first, second = sb.Bank(), sb.Bank()
    attached(monkeypatch, first, second)
    assert run(tmp_path, "--pilot") == ("exit", 0)
    raw = capsys.readouterr().out
    assert "More than one Bank of America tab is on Statements & Documents" in " ".join(raw.split())
    assert result(raw)["stopped"] == 1
    (written,) = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["step"] == "get the statements tab"
    assert report["reason"] == "several tabs are on the statements page"
    for tab in (first, second):
        assert tab.reloads == 0 and not tab.lists and not tab.pdfs and not tab.asked
