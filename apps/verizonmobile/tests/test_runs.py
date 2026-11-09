"""Whole runs, through the app's own main(), on a made-up signed-in tab of
Bill & payment history. No browser, no network, invented values only.

What these hold is how a run ends. A list that stops is never noted as
read whole, a sign-out partway stops the run once, another account shown
stops it before any bill of the wrong account is asked for, and each bill
reads the history once."""
import base64
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import verizonmobile_docs as docs  # noqa: E402
import verizonmobile_site as site  # noqa: E402
from paperpull_core.run_reporting import PREFIX  # noqa: E402

PDF_A = b"%PDF-1.4 ACCOUNT-A " + b"a" * 3000
PDF_B = b"%PDF-1.4 ACCOUNT-B " + b"b" * 3000
ACCOUNT_A = "1111111111-00001"
ACCOUNT_B = "2222222222-00001"
ENDS = ["10/11/2026", "09/11/2026", "08/11/2026"]


def cycle(end):
    return {"billEndDate": end, "billAmount": "$10.00",
            "cta": [{"label": "Review bill PDF", "link": ""}]}


def answer(ends, acct=ACCOUNT_A, name="Aaaaaa Account"):
    return {"responseInfo": {"responseCode": "00"},
            "body": {"billingHistory": {
                "billCycle": [cycle(e) for e in ends],
                "address": {"accountName": name, "accountNumber": acct, "state": "OR"}}}}


class Req:
    method = "GET"

    def all_headers(self):
        return {"channelid": "VZW-DOTCOM"}


class Resp:
    def __init__(self, data, status=200):
        self.url = site.BASE + site.HISTORY_API_PATH
        self.status, self._data = status, data
        self.request = Req()
        self.headers = {"content-type": "application/json"}

    def body(self):
        return json.dumps(self._data).encode()

    def json(self):
        return self._data


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n

    def inner_text(self, **k):
        return ""

    def all_inner_texts(self):
        return []


class Page:
    """A signed-in tab on Bill & payment history. `data` is what the page's
    own bill_history call answers, `pdf` what every bill_pdfdoc answers.
    With `signs_out`, the first bill's PDF is refused as a session that has
    ended, and every load after it shows the sign-in page. The PDFs of the
    end dates in `refuses` are refused while the history still reads, and
    `status` is what the history call answers with."""

    def __init__(self, data=None, asks=True, pdf=PDF_A, signs_out=False, refuses=(), status=200):
        self.data = answer(ENDS) if data is None else data
        self.asks, self.pdf, self.signs_out = asks, pdf, signs_out
        self.refuses, self.status = set(refuses), status
        self.signed_out = False
        self.url = site.HISTORY_URL
        self.handlers, self.asked, self.gotos = [], [], 0

    @property
    def context(self):
        return self

    @property
    def pages(self):
        return [self]

    def is_closed(self):
        return False

    def on(self, event, h):
        if event == "response":
            self.handlers.append(h)

    def remove_listener(self, event, h):
        if h in self.handlers:
            self.handlers.remove(h)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.gotos += 1
        if self.signed_out:
            self.url = "https://secure.verizon.com/signin"
            return
        self.url = url
        if self.asks:
            for h in list(self.handlers):
                h(Resp(self.data, self.status))

    def locator(self, sel):
        return Locator(1 if self.signed_out and "password" in sel else 0)

    def get_by_text(self, *a, **k):
        return Locator()

    def get_by_role(self, *a, **k):
        return Locator()

    def title(self):
        return "Bill history"

    def evaluate(self, js, arg=None):
        if isinstance(arg, list) and arg and str(arg[0]).startswith(site.BASE + site.PDF_PATH):
            self.asked.append(arg[0])
            if self.signs_out:
                self.signed_out = True
                return {"status": 401, "type": "text/html"}
            if any("startMonthDate=" + end.replace("/", "%2F") in arg[0] for end in self.refuses):
                return {"status": 403, "type": "text/html"}
            return {"status": 200, "type": "application/pdf",
                    "b64": base64.b64encode(self.pdf).decode()}
        return []


class Run:
    def __init__(self, tmp_path, monkeypatch, capsys, page):
        cfg = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
        cfg.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                    "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                    "delay_min_seconds": 0, "delay_max_seconds": 0, "min_pdf_bytes": 100})
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")
        self.out = Path(cfg["output_dir"])
        self.page, self.capsys = page, capsys

        def fake_page(app):
            app._work_page = self.page
            app._dl_dir = self.out / ".verizonmobile-downloads"
            return self.page
        monkeypatch.setattr(docs.App, "page", fake_page)
        monkeypatch.setattr(docs.App, "close", lambda app: None)
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))
        # The validator wants a whole PDF and these are bytes only. Which
        # bytes were saved where is what is checked here.
        from paperpull_core import receipt_pdf
        ok = type("R", (), {"ok": True, "size_bytes": 3000, "page_count": 1, "reason": ""})
        monkeypatch.setattr(receipt_pdf, "validate_pdf", lambda *_a, **_k: ok)

    def main(self, *args):
        self.capsys.readouterr()
        try:
            ended = ("returned", docs.main(["--config", str(self.cfg), *args]))
        except SystemExit as e:
            ended = ("exit", e.code)
        out = self.capsys.readouterr().out
        res = [json.loads(line[len(PREFIX):]) for line in out.splitlines() if line.startswith(PREFIX)]
        return " ".join(out.split()), (res[-1] if res else None), ended

    def _read(self, name):
        p = self.out / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def listing(self):
        return self._read("last-listing.json")

    def discovery(self):
        return self._read("discovery.json") or {}

    def progress(self):
        return self._read("progress.json") or {}

    def saved(self):
        return {p.name: p.read_bytes() for p in (self.out / "Statements").glob("*.pdf")}


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    return lambda page: Run(tmp_path, monkeypatch, capsys, page)


@pytest.mark.parametrize("page", [
    Page(asks=False),
    Page(data={"responseInfo": {"responseCode": "00"}, "body": {}}),
    Page(data=answer([])),
    Page(data=answer(ENDS + ["13/45/2026"])),
    Page(data=answer(ENDS + ["10/11/2026"])),
    Page(data=answer(ENDS, acct="")),
], ids=["never-asked", "no-billCycle", "no-bills", "one-malformed-row", "duplicate-end-date",
        "no-account-number"])
def test_a_list_that_stops_is_never_noted_whole(run, page):
    """The #124 shape. Each of these used to end with the listing noted
    whole, nothing listed and the run reported clean, so Pilot found nothing
    in scope and Resume called everything complete."""
    r = run(page)
    said, result, ended = r.main("--pilot")
    assert ended == ("exit", 1), said
    assert r.listing()["complete"] is False, said
    assert result["stopped"] == 1, said
    assert "stopped partway" in said and page.asked == []
    # Resume reads no list of its own, and after this one says so and
    # leaves as a run whose list was not read, asking for no bill.
    said, result, ended = r.main("--resume")
    assert result["stopped"] == 1 and result.get("list_not_read") == 1, said
    assert page.asked == [] and r.progress() == {}


def test_a_list_that_stops_keeps_the_bills_read_before_it(run):
    r = run(Page(data=answer(ENDS + ["13/45/2026"])))
    r.main("--discover")
    assert sorted(v["date"] for v in r.discovery().values()) == ["2026-08-11", "2026-09-11", "2026-10-11"]
    assert r.listing()["complete"] is False


def test_bills_are_recorded_by_account_and_end_date(run):
    r = run(Page())
    said, result, ended = r.main("--discover")
    assert ended[1] in (0, None) and r.listing()["complete"] is True, said
    assert sorted(r.discovery()) == ["id:bill-1111-00001-2026-08-11", "id:bill-1111-00001-2026-09-11",
                                     "id:bill-1111-00001-2026-10-11"]
    text = (r.out / "discovery.json").read_text(encoding="utf-8")
    assert "1111111111" not in text and "VZW-DOTCOM" not in text


def test_a_sign_out_partway_stops_the_run_once(run):
    """A refused bill used to send every bill to Manual Review, each with a
    failure file, and the run carried on to the end."""
    page = Page(signs_out=True)
    r = run(page)
    said, result, ended = r.main("--all", "--yes")
    assert len(page.asked) == 1, said
    assert result["manual_review"] == 0 and result["failed"] == 0, said
    assert result["stopped"] == 1 and "signed out" in said
    assert r.saved() == {} and r.progress() == {}


def test_another_account_shown_asks_for_none_of_its_bills(run):
    """Discover on account A, then the browser shows account B. Resume used
    to save B's PDFs under A's records as Completed."""
    page = Page(data=answer(ENDS, acct=ACCOUNT_A), pdf=PDF_A)
    r = run(page)
    r.main("--discover")
    page.data, page.pdf = answer(ENDS, acct=ACCOUNT_B, name="Bbbbbb Other"), PDF_B
    said, result, ended = r.main("--resume")
    assert page.asked == [], said
    assert "account ending 2222-00001" in said and "ending 1111-00001" in said
    assert result["stopped"] == 1 and result["manual_review"] + result["failed"] == 0
    assert r.saved() == {} and r.progress() == {}


def test_a_second_accounts_bills_are_its_own(run):
    """A full run on A, then one with B shown, used to skip all of B's bills
    as already downloaded."""
    page = Page(data=answer(ENDS, acct=ACCOUNT_A), pdf=PDF_A)
    r = run(page)
    r.main("--all", "--yes")
    assert len(page.asked) == 3 and set(r.saved().values()) == {PDF_A}
    page.data, page.pdf, page.asked = answer(ENDS, acct=ACCOUNT_B), PDF_B, []
    said, result, ended = r.main("--all", "--yes")
    assert len(page.asked) == 3 and said.count("Already downloaded") == 3, said
    saved = r.saved()
    assert sorted(saved.values()).count(PDF_A) == 3 and sorted(saved.values()).count(PDF_B) == 3
    # B's files take the names A's already hold, told apart by B's account.
    assert all("2222-00001" in name for name, data in saved.items() if data == PDF_B), sorted(saved)


# Account B's bills, each older than account A's newest.
B_ENDS = ["10/05/2026", "09/05/2026"]


def asked_for(page, end):
    return [u for u in page.asked if "startMonthDate=" + end.replace("/", "%2F") in u]


@pytest.mark.parametrize("second", [("--all", "--yes"), ("--resume",)], ids=["run-all", "resume"])
def test_a_bill_left_on_one_account_never_holds_back_the_account_shown(run, second):
    """Two accounts on one sign-in. Account A's newest bill was refused, so
    it was not done. A run with account B shown took every bill newest
    first, reached A's bill before any of B's, and stopped there, on every
    run, so B's older bills were never asked for. B's bills are taken first
    now, A's bill waits for a run with A shown, and the run still stops
    once, naming A, and reads the history no more often than before."""
    page = Page(data=answer(ENDS, acct=ACCOUNT_A), pdf=PDF_A, refuses={ENDS[0]})
    r = run(page)
    said, result, ended = r.main("--all", "--yes")
    refused = "id:bill-1111-00001-2026-10-11"
    assert len(page.asked) == 3 and result["failed"] == 1, said
    assert not r.progress()[refused].get("downloaded_ok")

    page.data, page.pdf, page.refuses = answer(B_ENDS, acct=ACCOUNT_B, name="Bbbbbb Other"), PDF_B, set()
    if second == ("--resume",):
        r.main("--discover")
    page.asked, page.gotos = [], 0
    said, result, ended = r.main(*second)
    assert [len(asked_for(page, end)) for end in B_ENDS] == [1, 1] and len(page.asked) == 2, said
    assert result["stopped"] == 1 and result["failed"] + result["manual_review"] == 0, said
    assert said.count("Choose the account ending 1111-00001") == 1, said
    # The listing or one read up front, each of B's bills, and A's bill,
    # which finds B shown and stops the run.
    assert page.gotos == 1 + len(B_ENDS) + 1, page.gotos
    assert not r.progress()[refused].get("downloaded_ok")
    assert sorted(r.saved().values()).count(PDF_B) == len(B_ENDS)

    page.data, page.pdf, page.asked = answer(ENDS, acct=ACCOUNT_A), PDF_A, []
    said, result, ended = r.main("--resume")
    assert len(page.asked) == 1 and asked_for(page, ENDS[0]), said
    assert not result.get("stopped") and r.progress()[refused].get("downloaded_ok") is True, said
    saved = sorted(r.saved().values())
    assert saved.count(PDF_A) == len(ENDS) and saved.count(PDF_B) == len(B_ENDS)


@pytest.mark.parametrize("cut,said_part,unread", [
    ({"status": 401}, "answered as signed out", False),
    ({"asks": False}, "could not be read again", True),
], ids=["signed-out", "list-stops"])
def test_a_resume_that_cannot_read_which_account_is_shown_stops_once(run, cut, said_part, unread):
    """With bills of two accounts left, a Resume reads the history once to
    learn which account is shown. A sign-out or a history that stops there
    stops the run as it would at a bill, with nothing asked for."""
    page = Page(data=answer(ENDS, acct=ACCOUNT_A), pdf=PDF_A)
    r = run(page)
    r.main("--discover")
    page.data = answer(B_ENDS, acct=ACCOUNT_B, name="Bbbbbb Other")
    r.main("--discover")
    for name, value in cut.items():
        setattr(page, name, value)
    said, result, ended = r.main("--resume")
    assert page.asked == [] and r.progress() == {}, said
    assert said_part in said and result["stopped"] == 1, said
    assert bool(result.get("list_not_read")) is unread, said


def test_each_bill_reads_the_history_once(run):
    """It used to be read twice a bill, once to open the page and again to
    find the bill, which on a site with bot protection doubles the loads."""
    page = Page()
    r = run(page)
    said, result, ended = r.main("--all", "--yes")
    assert result["new_files"] == len(ENDS), said
    assert page.gotos == 1 + len(ENDS), page.gotos


def test_login_says_success_only_when_the_bills_are_listed(run):
    said, _, _ = run(Page()).main("--login")
    assert "Success" in said
    for page in (Page(data=answer([])), Page(asks=False)):
        said, _, _ = run(page).main("--login")
        assert "Success" not in said and "did not list your bills" in said, said


def test_diagnose_says_whether_the_list_was_read_whole(run):
    """Diagnose reads the list as a run does and says in its file whether
    it was read whole, still writing the rest when it was not."""
    for page, whole, bills in ((Page(), True, 3), (Page(data=answer(ENDS + ["13/45/2026"])), False, 3),
                               (Page(data=answer([])), False, 0), (Page(asks=False), False, 0)):
        r = run(page)
        said, _, ended = r.main("--diagnose")
        info = json.loads((r.out / "Diagnostics" / "diagnose-billing.json").read_text(encoding="utf-8"))
        assert info["list_read_whole"] is whole, said
        assert len(info["bills_recognized"]) == bills and "unverified" not in info
        assert all(b["has_id"] for b in info["bills_recognized"])
        assert page.asked == [], "Diagnose downloads nothing"
