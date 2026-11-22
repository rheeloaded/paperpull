"""Records a build before 0.62.0 wrote with no bill id (#249). They name no
account, so download_bill never asks for them, and every run failed them
as documents that would not render, a Pilot's slots included. A run now
leaves them as they are and says so once, and a bill that does fail says
which way in its failure file. Invented values only."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_runs import ENDS, Page, Run, answer  # noqa: E402
import verizonmobile_docs as docs  # noqa: E402
import verizonmobile_site as site  # noqa: E402
from paperpull_core.failure import _step  # noqa: E402
from paperpull_core.words import shape_tree, words_for  # noqa: E402

LEFT = "bill record(s) from an earlier build name no account"


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    return lambda page: Run(tmp_path, monkeypatch, capsys, page)


def legacy(date, **more):
    rec = docs.Document(title="Verizon Mobile Bill %s" % date, category="Statement",
                        summary="Bill", date=date, document_id="").to_dict()
    rec["state"] = "discovered"
    rec.update(more)
    return rec


def seed(r, records, progress=None):
    """Discover once, then add the records as an earlier build left them."""
    r.main("--discover")
    known = r.discovery()
    for rec in records:
        known[docs.Document.from_dict(rec).key] = rec
    (r.out / "discovery.json").write_text(json.dumps(known), encoding="utf-8")
    if progress:
        kept = r.progress()
        kept.update(progress)
        (r.out / "progress.json").write_text(json.dumps(kept), encoding="utf-8")
    return {docs.Document.from_dict(rec).key: rec for rec in records}


def failures(r):
    return list((r.out / "Diagnostics").glob("failure-*.json"))


@pytest.mark.parametrize("how", [("--pilot",), ("--all", "--yes"), ("--resume",)])
def test_old_records_are_left_and_every_bill_saved(run, how):
    page = Page()
    r = run(page)
    old = seed(r, [legacy("2026-11-11"), legacy("2026-10-11"),
                   legacy("2026-10-12", document_id="bill-1111-00001-2026-10-09")])
    old_progress_key = next(iter(old))
    (r.out / "progress.json").write_text(json.dumps(
        {old_progress_key: {"state": "failed", "notes": "Could not capture the document PDF"}}),
        encoding="utf-8")
    before_discovery = {k: r.discovery()[k] for k in old}
    before_progress = r.progress()[old_progress_key]
    said, result, ended = r.main(*how)
    assert len(page.asked) == len(ENDS), said
    assert result["new_files"] == len(ENDS) and result["failed"] == 0, said
    assert len(r.saved()) == len(ENDS)
    assert failures(r) == [] and not (r.out / "Diagnostics" / "download-attempt.json").exists()
    assert said.count(LEFT) == 1 and ("3 " + LEFT) in said, said
    # Left exactly as they were.
    assert {k: r.discovery()[k] for k in old} == before_discovery
    assert r.progress()[old_progress_key] == before_progress
    assert all(k not in r.progress() for k in old if k != old_progress_key)


def test_old_records_never_take_a_pilots_place(run):
    page = Page()
    r = run(page)
    seed(r, [legacy("2026-12-11"), legacy("2026-11-11")])
    r.cfg.write_text(json.dumps(dict(json.loads(r.cfg.read_text(encoding="utf-8")),
                                     pilot_count=2)), encoding="utf-8")
    said, result, _ = r.main("--pilot")
    assert result["new_files"] == 2 and result["failed"] == 0, said
    assert len(page.asked) == 2 and failures(r) == []


@pytest.mark.parametrize("doc_id,date", [
    ("bill-1111-00001-2026-10-11", "2026-10-12"), ("bill-111-2026-10-11", "2026-10-11"),
    ("bill-1111-2026-10-11x", "2026-10-11"), (" bill-1111-2026-10-11", "2026-10-11"),
    ("id:bill-1111-2026-10-11", "2026-10-11"), ("BILL-1111-2026-10-11", "2026-10-11"),
    ("", "2026-10-11"), (None, "2026-10-11"), (7, "2026-10-11"),
])
def test_a_run_and_download_bill_agree_on_which_records_are_bills(doc_id, date):
    """One predicate. What a run leaves out is exactly what download_bill
    would refuse before it opens the history."""
    assert site.recorded_bill(doc_id, date) == ""
    page = Page()
    trace = []
    assert site.download_bill(page, None, date, "unused.pdf", trace=trace,
                              document_id=doc_id) is False
    assert page.gotos == 0 and trace == [{"note": "no recorded bill"}]


@pytest.mark.parametrize("doc_id,date,account", [
    ("bill-1111-00001-2026-10-11", "2026-10-11", "1111-00001"),
    ("bill-1111-2026-10-11", "2026-10-11", "1111"),
])
def test_a_bill_id_of_either_shape_is_a_bill(doc_id, date, account):
    assert site.recorded_bill(doc_id, date) == account


def test_an_account_with_no_suffix_saves_every_bill_and_says_nothing(run):
    page = Page(data=answer(ENDS, acct="1111111111"))
    r = run(page)
    said, result, _ = r.main("--all", "--yes")
    assert result["new_files"] == len(ENDS) and LEFT not in said, said
    assert page.gotos == 1 + len(ENDS) and failures(r) == []


def test_a_done_old_record_is_left_too_and_its_bill_still_saved(run):
    page = Page()
    r = run(page)
    old = seed(r, [legacy("2026-10-11")])
    key = next(iter(old))
    done = {"state": "completed", "downloaded_ok": True, "pdf_path": ""}
    (r.out / "progress.json").write_text(json.dumps({key: done}), encoding="utf-8")
    said, result, _ = r.main("--all", "--yes")
    assert ("1 " + LEFT) in said and result["new_files"] == len(ENDS), said
    assert r.progress()[key] == done
    # The id record of that day keeps the plain name, nothing is told apart.
    assert "id:bill-1111-00001-2026-10-11" in r.progress()
    assert all("1111-00001" not in name for name in r.saved())


def test_a_stopped_pilot_then_resume_leaves_the_old_records(run):
    page = Page(signs_out=True)
    r = run(page)
    old = seed(r, [legacy("2026-11-11")])
    said, result, _ = r.main("--pilot")
    assert result["stopped"] == 1 and len(page.asked) == 1, said
    assert not any(k.startswith("id:") for k in r.progress())
    page.signs_out = page.signed_out = False
    page.url = site.HISTORY_URL
    said, result, _ = r.main("--resume")
    assert result["new_files"] == len(ENDS) and said.count(LEFT) == 1, said
    said, result, _ = r.main("--resume")
    assert len(page.asked) == 1 + len(ENDS) and LEFT in said and failures(r) == [], said
    assert r.discovery()[next(iter(old))] == old[next(iter(old))]


# -- the failure file says which way a bill was not saved -----------------------

def _failure(r):
    (written,) = failures(r)
    return json.loads(written.read_text(encoding="utf-8")), written.read_text(encoding="utf-8")


def _kept(value):
    return shape_tree(value, words_for("Verizon Mobile"), full_list=True) == value


def test_a_record_with_no_bill_says_so(run, monkeypatch):
    page = Page()
    r = run(page)
    r.main("--discover")
    # Asked directly, as a record the run left out would have been asked.
    monkeypatch.setattr(docs.App, "_select", lambda app, limit=None: [
        docs.Document.from_dict(legacy("2026-10-11"))])
    said, result, _ = r.main("--all", "--yes")
    report, text = _failure(r)
    assert report["reason"] == "the record has no bill id", said
    assert report["extra"]["postmortem"]["bill_notes"] == ["no recorded bill"]
    assert page.asked == []


def test_a_bill_gone_from_the_history_says_so(run):
    page = Page()
    r = run(page)
    r.main("--discover")
    page.data = answer(ENDS[1:])
    said, result, _ = r.main("--resume")
    report, _ = _failure(r)
    assert report["reason"] == "no bill in the history has its id", said
    assert report["extra"]["postmortem"]["bills_matched"] == 0


class Answers(Page):
    def __init__(self, got, **k):
        super().__init__(**k)
        self.got = got

    def evaluate(self, js, arg=None):
        if isinstance(arg, list) and arg and str(arg[0]).startswith(site.BASE + site.PDF_PATH):
            self.asked.append(arg[0])
            return dict(self.got)
        return []


@pytest.mark.parametrize("got,reason,status", [
    ({"status": 404, "type": "text/x-zq-invented"}, "the bill answered with a status", 404),
    ({"status": 200, "type": "text/x-zq-invented", "b64": "WlpaWlo="}, "the bill was not a pdf", 200),
])
def test_a_fetch_that_brings_no_pdf_says_how(run, got, reason, status):
    page = Answers(got)
    r = run(page)
    said, result, _ = r.main("--pilot")
    assert result["failed"] == len(ENDS), said
    report, text = _failure(r)
    assert report["reason"] == reason
    facts = report["extra"]["postmortem"]
    assert facts["pdf_status"] == status and facts["bill_notes"] == ["fetched"]
    for value in ("x-zq-invented", site.HOST, "1111111111", "VZW-DOTCOM", "Dana"):
        assert value not in text and value not in json.dumps(facts), value
    assert (r.out / "Diagnostics" / "download-attempt.json").exists()


def test_a_refused_bill_says_it_was_refused(run):
    page = Page(refuses={ENDS[0]})
    r = run(page)
    said, result, _ = r.main("--pilot")
    assert result["failed"] == 1 and result["new_files"] == len(ENDS) - 1, said
    report, _ = _failure(r)
    assert report["reason"] == "the bill was refused while the history still reads"
    assert report["extra"]["postmortem"]["pdf_status"] == 403
    assert report["extra"]["postmortem"]["bill_notes"] == ["fetched", "refused the history still reads"]


@pytest.mark.parametrize("trace", [
    [{"note": "no recorded bill"}],
    [{"note": "no single bill matches the record", "matches": 2}],
    [{"note": "fetched", "host": site.HOST, "status": 404, "type": "text/html"}],
    [{"note": "fetched", "host": site.HOST, "status": 200, "type": "text/html"}],
    [{"note": "fetched", "host": site.HOST, "status": 403, "type": "text/html"},
     {"note": "refused, the history still reads"}],
    [{"note": "too large for a bill"}], [{"note": "fetch failed", "error": "TimeoutError"}],
    [], None, ["x", 5, {"note": None}],
])
def test_every_reason_and_fact_keeps_its_words(trace):
    reason, facts = docs.why_not_saved(trace)
    assert _step(reason) == reason and _kept(reason), reason
    assert _kept(facts), facts
    assert "text/html" not in json.dumps(facts) and site.HOST not in json.dumps(facts)
