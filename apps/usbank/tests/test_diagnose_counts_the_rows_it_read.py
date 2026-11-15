"""What U.S. Bank's Diagnose read is counted, printed and kept apart from an error.

Its Diagnose wrote the rows it collected under "collected_generic" and the
statements its own reader read under "statements_read", and printed
"Rows collected" from "collected", which it never wrote, so the line always
read "Rows collected: ?". The year picker line read "year_options", which it
never wrote either, so it never showed. And the core read only "collected"
for whether a report read anything, so a report that read rows on a page
where a sign-in check also tripped ended as one that read nothing, telling
the person to sign in. Its reader's error went under "statements_read" too,
where a count goes.

Here Diagnose runs whole against a made-up page, the site's reading of it
stood in for. No real account, no network, every value invented.
"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usbank_docs as docs  # noqa: E402
import usbank_site as site  # noqa: E402
from paperpull_core import run_reporting, words  # noqa: E402


class _None:
    def count(self):
        return 0


class _Page:
    url = site.BASE + "/digital/servicing/statements"

    def is_closed(self):
        return False

    def title(self):
        return "Statements"

    def locator(self, *_):
        return _None()

    def get_by_role(self, _role):
        return _None()

    def screenshot(self, **_):
        return b"\x89PNG\r\n\x1a\n"

    def wait_for_timeout(self, _ms):
        pass


ROWS = [site.RawDoc(title="Statement", date_text="Oct 9, 2031", text="Statement Oct 9, 2031"),
        site.RawDoc(title="Statement", date_text="Sep 9, 2031", text="Statement Sep 9, 2031"),
        site.RawDoc(title="Statement", date_text="Aug 9, 2031", text="Statement Aug 9, 2031")]


def _app(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                               "profile_dir": str(tmp_path / "profile")}), encoding="utf-8")
    with mock.patch.object(docs.App, "_setup_logging", lambda self: None):
        app = docs.App(docs.build_parser().parse_args(["--config", str(cfg)]))
    page = _Page()
    app.page = lambda: page
    return app


def _diagnose(app, *, signed_out=True, rows=ROWS, read=None, read_error=None,
              periods=("2031", "2030")):
    def read_rows(_page, account=""):
        if read_error is not None:
            raise read_error
        return site.Read(list(rows[:2]) if read is None else read)
    with mock.patch.multiple(
            site,
            goto_documents=lambda _p: True,
            looks_signed_out=lambda _p: signed_out,
            detect_security_challenge=lambda _p: None,
            expand_all=lambda _p: None,
            scroll_full_page=lambda _p: None,
            reset_to_newest_period=lambda _p: "2031",
            collect_documents=lambda _p, or_raise=False: list(rows),
            account_name=lambda _p: "Checking",
            read_rows=read_rows,
            describe_selects=lambda _p: [],
            account_select=lambda _p: (None, []),
            year_select=lambda _p: (None, list(periods)),
            card_groups=lambda _p: [],
            period_options=lambda _p: site.Read(list(periods)),
            probe_api=lambda _p: [],
            probe_statements_api=lambda _p: None):
        app.cmd_diagnose()
    return json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))


def test_a_report_that_read_rows_is_saved_though_a_sign_in_check_tripped(tmp_path):
    app = _app(tmp_path)
    info = _diagnose(app)
    assert "error" not in info, info.get("error")
    assert info["signed_out"] is True
    assert info["collected_generic"] == 3 and info["statements_read"] == 2
    assert not words.read_nothing_in(app.paths.diagnostics)


def test_a_report_on_a_sign_in_page_still_reads_nothing(tmp_path):
    app = _app(tmp_path)
    _diagnose(app, rows=[], read=[])
    with pytest.raises(SystemExit) as out:
        app.write_survey()
    assert out.value.code == run_reporting.NOTHING_READ


def test_rows_its_own_reader_read_count_when_the_generic_read_found_none(tmp_path):
    app = _app(tmp_path)
    _diagnose(app, rows=[], read=list(ROWS[:2]))
    assert not words.read_nothing_in(app.paths.diagnostics)


def test_what_it_prints_is_what_it_read(tmp_path, capsys):
    app = _app(tmp_path)
    _diagnose(app, signed_out=False)
    said = capsys.readouterr().out
    assert "Rows collected: 3" in said, said
    assert "Rows collected: ?" not in said
    assert "Year picker:" in said, said


def test_a_reader_that_failed_writes_its_error_apart_from_the_count(tmp_path, capsys):
    """The error goes where the other apps put theirs, and a signed-out
    report whose generic read found nothing still reads nothing."""
    app = _app(tmp_path)
    info = _diagnose(app, rows=[], read_error=site.RowUnread("the statement list would not answer"))
    assert "statements_read" not in info, info
    # The file shapes what is not on the word list, ERR among it.
    assert "the statement list would not" in info["collect_error"], info["collect_error"]
    with pytest.raises(SystemExit) as out:
        app.write_survey()
    assert out.value.code == run_reporting.NOTHING_READ


def test_a_year_picker_that_read_nothing_prints_no_line(tmp_path, capsys):
    app = _app(tmp_path)
    _diagnose(app, signed_out=False, periods=())
    said = capsys.readouterr().out
    assert "Year picker:" not in said
