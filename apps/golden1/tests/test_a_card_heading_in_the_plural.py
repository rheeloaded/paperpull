"""A card under a heading in the plural (#35).

RECORDED, from the member's answer of 2026-09-30. His card's panel is headed
"Credit Cards / Home Equity Lines of Credit" and a masked number of stars
with no digits. The app looked for card as a whole word, so the plural
slipped by, the card was read as an account, and its statements were saved
as Account Statement. He calls it his credit card throughout the issue.

Now "credit cards" counts, and only a panel the plural alone reads as a card
changes. It takes the key its own heading gives it, every other panel keeps
the key 0.41.0 gave it, and the statements it saved under a key its own
heading gave are carried to the card's on the next Discover, keeping their
downloaded state, so Rename renames the files and nothing is fetched twice.
A review before release found the first repair carrying records from a key
another panel may hold, and fetching statements twice after a stopped save.
Those pages are here too. Every date, heading and file here is invented.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
from paperpull_core import doc_types, renaming
from paperpull_core.models import State
from paperpull_core.storage import CsvFile, JsonStore

import golden1_docs
import golden1_site as site
import test_accounts_and_pages as shaped

HEADING = "Credit Cards / Home Equity Lines of Credit - ******"
PLURAL = HEADING
CHECKING = "Everyday Checking ****1234"
SAVINGS = "Share Savings ****5678"
VISA = "VISA SIGNATURE CARD ****4321"
AUTO = "Auto Loan"
PLURAL_VENDOR = (shaped.VENDOR
                 .replace("VISA SIGNATURE CARD ****4321", HEADING)
                 .replace('<h3 id="h1">Visa Signature</h3>',
                          '<h3 id="h1">Credit Cards / Home Equity Lines of Credit</h3>'))
# His card's own key, the heading's words, which is also what its statements
# were saved under as the second panel of the account kind.
OWN = site._words_key({"heading": HEADING})


def test_the_vendor_here_has_his_heading():
    assert HEADING in PLURAL_VENDOR and "VISA" not in PLURAL_VENDOR
    assert OWN == "account credit cards home equity lines o"


def test_a_card_heading_in_the_plural_is_read_as_a_card():
    assert site.CARD_PANEL_RE.search(HEADING)
    assert site._heading_words(HEADING) == ["card", "credit", "equity", "line"]


@pytest.mark.parametrize("heading", [
    "VISA SIGNATURE CARD ****4321", "Mastercard", "Credit Card", "Member Statements",
    "Share Savings", "Cardinal Club Savings", "Checking and Savings", "Auto Loan",
    "Checking & Debit Cards", "Gift Cards", "Business Cards & Loans"])
def test_every_other_heading_reads_as_it_did(heading):
    assert bool(site.CARD_PANEL_RE.search(heading)) == \
        bool(site._CARD_PANEL_RE_SINGULAR.search(heading)), heading


def test_a_heading_word_reaches_a_trace_only_as_the_list_writes_it():
    assert site._heading_words("ſAVINGS Statements") == ["savings", "statements"]


# -- which panel changes, and what it carries -------------------------------------

def _kinds(*headings):
    panels = [{"i": i, "heading": h} for i, h in enumerate(headings)]
    site._assign_kinds(panels)
    return panels


def test_his_page_moves_only_the_card():
    checking, card = _kinds("Member Statements", HEADING)
    assert (checking["card"], checking["account_key"], checking["legacy"]) == (False, "", None)
    assert (card["card"], card["account_key"]) == (True, OWN)
    assert card["legacy"] == (site.ACCOUNT_TITLE, OWN), "saved under its own heading's key"


def test_a_card_and_a_line_under_one_heading_are_left_as_they_were():
    """Neither can be told from the other, and a key shared by both would
    pass one's statements to the other."""
    panels = _kinds("Member Statements", HEADING, HEADING)
    assert [p["card"] for p in panels] == [False, False, False]
    assert [p["account_key"] for p in panels] == ["", "account 2", "account 3"]


def test_a_card_saved_first_carries_nothing_from_the_empty_key():
    """The empty key goes to whichever panel is first, so what sits there
    may be another panel's, saved while the page was different."""
    card, checking = _kinds(HEADING, CHECKING)
    assert (card["card"], card["account_key"], card["legacy"]) == (True, OWN, None)
    assert (checking["card"], checking["account_key"]) == (False, "account ending 1234")


def test_a_card_the_singular_read_keeps_its_key_when_a_plural_one_is_listed_first():
    plural, visa = _kinds(HEADING, VISA)
    assert (visa["card"], visa["account_key"]) == (True, "")
    assert (plural["card"], plural["account_key"]) == (True, OWN)


# -- in a browser, the vendor test_accounts_and_pages makes up ---------------------

@pytest.fixture()
def vendor(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    pg.set_content(PLURAL_VENDOR)
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "open_vendor", lambda page: pg)
    yield pg
    browser.close()
    driver.stop()


def test_its_statements_are_card_statements_that_know_their_old_title(vendor):
    docs = site.collect_download_docs(vendor, trace=[])
    card = [d for d in docs if d.title.startswith(site.CARD_TITLE)]
    member = [d for d in docs if d.title.startswith(site.ACCOUNT_TITLE)]
    assert len(card) == 15 and len(member) == 26, (len(card), len(member))
    for d in card:
        assert d.account == OWN
        assert d.legacy_title == d.title.replace(site.CARD_TITLE, site.ACCOUNT_TITLE, 1)
        assert d.legacy_account == OWN
    assert all(d.account == "" for d in member)
    assert not any(d.legacy_title or d.legacy_account for d in member), \
        "nothing of the checking account's moves"


def test_discover_says_the_card_was_taken_for_a_card(vendor):
    trace: list = []
    site.collect_download_docs(vendor, trace=trace)
    lines = site.discovery_lines(trace)
    assert any("2 account(s), 1 taken for a card" in line for line in lines), lines
    assert any("card, credit, equity, line" in line for line in lines), lines


def test_a_carried_statement_downloads_from_the_cards_panel(vendor, tmp_path):
    out = tmp_path / "s.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2025-08-20", out,
                              title="Credit Card Statement - August 20, 2025",
                              account=OWN, trace=trace), trace
    assert b"invented card statement 08/20/25" in out.read_bytes()


# -- carrying what was saved, with the app's own stores and index ------------------

def old_panels(*headings):
    """The panels as 0.41.0 read them, the singular rule and places."""
    panels = [{"i": i, "heading": h,
               "card": bool(site._CARD_PANEL_RE_SINGULAR.search(h))} for i, h in enumerate(headings)]
    for p in panels:
        p["account_key"] = site._account_by_place(panels, p)
    return panels


def raw_docs(page, listing):
    """What _read_every_panel returns for `page` now, where listing[i] is the
    dates panel i lists, legacy fields and all."""
    site._assign_kinds(page)
    seen, out = set(), []
    for p in page:
        kind = site.CARD_TITLE if p["card"] else site.ACCOUNT_TITLE
        account = site._panel_account(page, p)
        legacy = p["legacy"]
        for iso in listing.get(p["i"], []):
            if (kind, account, iso) in seen:
                continue
            seen.add((kind, account, iso))
            disp = site._human_date(iso)
            r = site.RawDoc(title=f"{kind} - {disp}", account=account, date_text=iso,
                            text=f"Golden 1 {kind} {disp}", kind="statement",
                            dated_by="label",
                            legacy_title=f"{legacy[0]} - {disp}" if legacy else "",
                            legacy_account=legacy[1] if legacy else "")
            r.heading = p["heading"]    # which panel listed it, for the checks here
            out.append(r)
    return out


def now(*headings):
    return [{"i": i, "heading": h} for i, h in enumerate(headings)]


def make_app(tmp_path):
    app = golden1_docs.App.__new__(golden1_docs.App)
    app.args = types.SimpleNamespace(start_date=None, redownload=False, end_date=None,
                                     year=None, type=None, max_docs=None)
    app.config = {"document_types": ["Statement", "Tax Document"], "max_path_length": 240,
                  "min_pdf_bytes": 10}
    app.rules = doc_types.load_rules()
    app.stats = {"skipped_out_of_scope": 0, "discovered": 0}
    (tmp_path / "backups").mkdir(exist_ok=True)
    app.discovery = JsonStore(tmp_path / "discovery.json", tmp_path / "backups")
    app.progress = JsonStore(tmp_path / "progress.json", tmp_path / "backups")
    app.discovery.load()
    app.progress.load()
    app.index_csv = CsvFile(tmp_path / "index.csv", storage.DOCUMENT_INDEX_COLUMNS,
                            tmp_path / "backups")
    app._listed_keys = set()
    app._carried = []
    return app


def save_as_0410(app, folder, page_then, listing):
    """Records, index rows and files as 0.41.0 left them for `page_then`,
    every listed statement saved. Each file holds its panel's heading."""
    for p in page_then:
        kind = site.CARD_TITLE if p["card"] else site.ACCOUNT_TITLE
        for iso in listing.get(p["i"], []):
            disp = site._human_date(iso)
            title = f"{kind} - {disp}"
            category, summary, conf = doc_types.classify_document(title, app.rules)
            doc = golden1_docs.Document(title=title, category=category, summary=summary,
                                        date=iso, confidence=conf, account=p["account_key"])
            rec = doc.to_dict()
            name = storage.build_pdf_filename(iso, summary, "", record=rec)
            path = storage.unique_path(folder, name)
            path.write_bytes(b"%PDF-1.7 " + p["heading"].encode() + b" " + iso.encode())
            rec.update(state=State.COMPLETED.value, downloaded_ok=True,
                       pdf_filename=path.name, pdf_path=str(path))
            app.index_csv.append_rows([{
                "Document Date": iso, "Category": category, "Document Summary": summary,
                "Document Title": title, "PDF Filename": path.name,
                "PDF Full Path": str(path), "Processing Status": "Completed"}])
            app.progress.data[doc.key] = dict(rec)
            app.discovery.data[doc.key] = dict(rec)
    app.discovery.save()
    app.progress.save()


def discover(app, docs, monkeypatch):
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "collect_download_docs", lambda page, trace=None: list(docs))
    app.page = lambda: object()
    app.check_session = lambda page: None
    return app.cmd_discover(quiet=True)


def whose(path):
    """Which panel a saved file came from, read from the invented PDF bytes."""
    return Path(path).read_bytes().split(b" ", 1)[1].rsplit(b" ", 1)[0].decode()


def named_for_their_owner(folder):
    for p in folder.iterdir():
        owner = whose(p)
        if "Credit Card" in p.name:
            assert owner in (PLURAL, VISA), (p.name, owner)


def not_done_by_another(app, docs):
    """Every statement listed now that counts as done is done with its own
    panel's file, never another's."""
    for r in docs:
        category, _, _ = doc_types.classify_document(r.title, app.rules)
        key = golden1_docs.Document(title=r.title, category=category, date=r.date_text,
                                    account=r.account).key
        rec = app.progress.get(key)
        if rec and rec.get("downloaded_ok"):
            assert whose(rec["pdf_path"]) == r.heading, (r.title, r.heading, rec)


def test_his_page_carries_and_renames(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-31", "2026-07-31"], 1: ["2026-08-20", "2026-07-20"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL), listing)
    docs = raw_docs(now(CHECKING, PLURAL), listing)
    assert discover(app, docs, monkeypatch) == 0
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    names = sorted(p.name for p in folder.iterdir())
    assert "2026-08-20 Golden 1 Credit Card Statement.pdf" in names, (names, said)
    assert "2026-08-31 Golden 1 Account Statement.pdf" in names, names
    named_for_their_owner(folder)
    for rec in app.progress.data.values():
        doc = golden1_docs.Document.from_dict(rec)
        assert rec.get("downloaded_ok") and app._already_done(doc), rec
    not_done_by_another(app, docs)


def test_a_second_discover_moves_nothing_more(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-31"], 1: ["2026-08-20", "2026-07-20"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL), listing)
    discover(app, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    before = (dict(app.discovery.data), dict(app.progress.data))
    again = make_app(tmp_path)
    assert discover(again, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch) == 0
    assert sorted(again.discovery.data) == sorted(before[0])
    assert sorted(again.progress.data) == sorted(before[1])
    assert not again._carried


def test_a_stop_between_the_two_saves_does_not_fetch_the_card_again(tmp_path, monkeypatch):
    """Discover carries the records and progress.json cannot be written, a
    sync client or a scanner holding it, or the window closed. The next
    Discover finishes the move, and a saved statement is not downloaded a
    second time (review before release)."""
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-31"], 1: ["2026-08-20", "2026-07-20"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL), listing)

    def locked(backup=False):
        raise PermissionError("progress.json is locked")

    app.progress.save = locked
    with pytest.raises(PermissionError):
        discover(app, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    again = make_app(tmp_path)
    discover(again, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    card = [golden1_docs.Document.from_dict(r) for r in again.discovery.data.values()
            if r["title"].startswith(site.CARD_TITLE)]
    assert len(card) == 2
    assert all(again._already_done(d) for d in card), "downloaded a second time"


def test_a_stop_after_progress_is_saved_finishes_the_move_next_time(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-31"], 1: ["2026-08-20"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL), listing)

    def locked():
        raise PermissionError("discovery.json is locked")

    app.discovery.save = locked
    with pytest.raises(PermissionError):
        discover(app, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    again = make_app(tmp_path)
    discover(again, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    titles = sorted(r["title"] for r in again.discovery.data.values())
    assert titles == ["Account Statement - August 31, 2026",
                      "Credit Card Statement - August 20, 2026"], titles
    card = [golden1_docs.Document.from_dict(r) for r in again.discovery.data.values()
            if r["title"].startswith(site.CARD_TITLE)]
    assert all(again._already_done(d) for d in card)


def test_a_locked_index_is_put_right_on_the_next_discover(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-31"], 1: ["2026-08-20"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL), listing)

    def locked(rows):
        raise PermissionError("the index is open in another program")

    app.index_csv.rewrite = locked
    discover(app, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    again = make_app(tmp_path)
    discover(again, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    renaming.run_for(again, apply_changes=True, say=lambda *_: None)
    assert "2026-08-20 Golden 1 Credit Card Statement.pdf" in [p.name for p in folder.iterdir()]
    named_for_their_owner(folder)


def test_a_card_new_on_the_page_takes_no_other_accounts_file(tmp_path, monkeypatch):
    """Saved while the page held Checking and Savings. A card opened since is
    listed first under the plural heading and shares a day with Checking.
    No checking statement takes the card's name, and the card's statement
    is not marked done by Checking's (review before release)."""
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    save_as_0410(app, folder, old_panels(CHECKING, SAVINGS),
                 {0: ["2026-08-31", "2026-07-31"], 1: ["2026-08-31"]})
    docs = raw_docs(now(PLURAL, CHECKING, SAVINGS),
                    {0: ["2026-09-30", "2026-08-31"], 1: ["2026-08-31", "2026-07-31"],
                     2: ["2026-08-31"]})
    discover(app, docs, monkeypatch)
    renaming.run_for(app, apply_changes=True, say=lambda *_: None)
    named_for_their_owner(folder)
    not_done_by_another(app, docs)
    card_aug = [golden1_docs.Document.from_dict(r) for r in app.discovery.data.values()
                if r["title"].startswith(site.CARD_TITLE) and r["date"] == "2026-08-31"]
    assert card_aug and not app._already_done(card_aug[0])


def test_a_card_saved_first_is_listed_again_and_takes_nothing(tmp_path, monkeypatch):
    """What its statements sit under is the empty key, which whichever panel
    is first holds, so they are not carried. They are listed again under the
    card's own key, and nothing of Checking's moves. A second copy under the
    card's name is the price of never passing one account's statement to
    another."""
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-31", "2026-07-20"], 1: ["2026-08-31", "2026-07-31"]}
    save_as_0410(app, folder, old_panels(PLURAL, CHECKING), listing)
    docs = raw_docs(now(PLURAL, CHECKING), listing)
    assert discover(app, docs, monkeypatch) == 2
    renaming.run_for(app, apply_changes=True, say=lambda *_: None)
    named_for_their_owner(folder)
    not_done_by_another(app, docs)
    checking = [golden1_docs.Document.from_dict(r) for r in app.progress.data.values()
                if r.get("account") == "account ending 1234"]
    assert len(checking) == 2 and all(app._already_done(d) for d in checking)


def test_a_plural_card_listed_before_a_visa_takes_none_of_its_statements(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-20", "2026-07-20"], 1: ["2026-08-20", "2026-07-15"]}
    save_as_0410(app, folder, old_panels(PLURAL, VISA), listing)
    docs = raw_docs(now(PLURAL, VISA), listing)
    discover(app, docs, monkeypatch)
    not_done_by_another(app, docs)
    visa = [golden1_docs.Document.from_dict(r) for r in app.progress.data.values()
            if r.get("account") == "" and r["title"].startswith(site.CARD_TITLE)]
    assert len(visa) == 2 and all(whose(r.pdf_path) == VISA for r in visa)
    plural = [golden1_docs.Document.from_dict(r) for r in app.discovery.data.values()
              if r.get("account") == OWN]
    assert len(plural) == 2 and not any(app._already_done(d) for d in plural)


def test_loans_told_apart_by_place_keep_their_places(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    then = {0: ["2026-08-31"], 1: ["2026-08-20"], 2: ["2026-08-15", "2026-07-15"],
            3: ["2026-07-15"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL, AUTO, AUTO), then)
    listed = dict(then)
    listed[3] = ["2026-08-15", "2026-07-15"]
    docs = raw_docs(now(CHECKING, PLURAL, AUTO, AUTO), listed)
    discover(app, docs, monkeypatch)
    new = [golden1_docs.Document.from_dict(r) for r in app.discovery.data.values()
           if r["date"] == "2026-08-15" and r["account"] == "account 4"]
    assert len(new) == 1 and not app._already_done(new[0]), "the second loan's new one downloads"
    first = [r for r in app.progress.data.values()
             if r["date"] == "2026-08-15" and r["account"] == "account 3"]
    assert len(first) == 1 and first[0].get("downloaded_ok") and whose(first[0]["pdf_path"]) == AUTO
    not_done_by_another(app, docs)


def test_a_checking_account_opened_since_downloads_its_own(tmp_path, monkeypatch):
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    save_as_0410(app, folder, old_panels(PLURAL), {0: ["2026-08-31", "2026-07-20"]})
    docs = raw_docs(now(PLURAL, CHECKING),
                    {0: ["2026-08-31", "2026-07-20"], 1: ["2026-08-31"]})
    discover(app, docs, monkeypatch)
    checking = [golden1_docs.Document.from_dict(r) for r in app.discovery.data.values()
                if r.get("account") == "account ending 1234"]
    assert len(checking) == 1 and not app._already_done(checking[0])
    not_done_by_another(app, docs)


def test_an_index_row_moves_only_with_its_own_file(tmp_path, monkeypatch):
    """Another account can hold a statement of the old kind on the same day,
    under the same title. Its row keeps its title."""
    folder = tmp_path / "Statements"
    folder.mkdir()
    app = make_app(tmp_path)
    listing = {0: ["2026-08-20"], 1: ["2026-08-20"]}
    save_as_0410(app, folder, old_panels(CHECKING, PLURAL), listing)
    discover(app, raw_docs(now(CHECKING, PLURAL), listing), monkeypatch)
    rows = app.index_csv.read_all()
    by_owner = {whose(r["PDF Full Path"]): r["Document Title"] for r in rows}
    assert by_owner[CHECKING] == "Account Statement - August 20, 2026"
    assert by_owner[PLURAL] == "Credit Card Statement - August 20, 2026"
