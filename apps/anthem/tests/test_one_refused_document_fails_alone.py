"""One EOB Anthem refuses on its own fails alone, and only a list refused
after it is a sign-out.

A 401, a 403, an answer with no session headers or a sign-in page where one
EOB's PDF should be was read as a sign-out, so the run stopped at that EOB.
An EOB Anthem refuses on its own is refused on every run, so every run
stopped there, and Continue stopped at it again, the loop of #124. Now the
claim type's list is read again with the call that proves a session. A list
refused too stops the run as signed out, as before. A list that still reads
leaves that EOB failed with nothing saved, the run goes on, and the next run
tries it again. The EOB is never asked for after the list is read again.
Every name, claim number, token and page word here is invented.
"""
import base64
import json
import logging
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core import testkit  # noqa: E402
from test_a_claim_number_shown_beside_its_token import (  # noqa: E402
    FakePage, claim_row, signed_in)

site = app_mod.site

PAGE_WORDS = b"made-up page words 4417"
SIGN_IN_PAGE = (b"<!doctype html><html><title>Sign in</title>"
                b"<input type=\"password\"><p>" + PAGE_WORDS + b"</p></html>")

# What one EOB's PDF can be answered with that read as a sign-out.
REFUSALS = {
    "401": {"status": 401},
    "403": {"status": 403},
    "no session headers": {"status": 0, "noauth": True},
    "sign-in page": {"status": 200, "b64": base64.b64encode(SIGN_IN_PAGE).decode()},
}

# The claim numbers, tokens and EOB ids of three invented claims.
CLAIMS = [("9000000AA000%d" % n, "e_" + ("%d0" % n) * 67, "Z_" + ("%d1" % n) * 95)
          for n in (1, 2, 3)]
REFUSED = CLAIMS[1]


def rows():
    return {"Medical": [claim_row(claim_number=number, claim_token=token, eob_id=eob)
                        for number, token, eob in CLAIMS]}


def doc_id(claim=REFUSED):
    return "Medical|%s|EOB|2" % claim[0]


class Refuses(FakePage):
    """Answers the summary with the rows given and every EOB's PDF, except
    the refused claim's, which is answered as `refusal` says. With
    `signs_out`, the session ends at that refusal, so the summary after it
    is refused as well, by `signs_out`'s answer. Notes every call in
    order."""

    def __init__(self, rows_by_type, refusal, signs_out=None, pdf=b"%PDF-1.4 invented"):
        super().__init__(rows_by_type)
        self.refusal, self.signs_out, self.pdf = refusal, signs_out, pdf
        self.calls, self.ended = [], False

    def evaluate(self, js, arg=None):
        if "eob.v1.summary" in js:
            self.calls.append("list")
            if self.ended:
                return dict(self.signs_out)
            return super().evaluate(js, arg)
        if "eob.v1.download" in js:
            self.calls.append("eob " + arg["claimId"])
            self.downloads.append(dict(arg))
            if arg["claimId"] == REFUSED[1]:
                self.ended = self.signs_out is not None
                return dict(self.refusal)
            return {"status": 200, "b64": base64.b64encode(self.pdf).decode()}
        raise AssertionError("an unexpected call into the page")


def asked(refusal) -> list:
    """The calls one refused EOB makes when the list still reads. A refusal
    by status asks once more with the session's headers taken again, as it
    always has, and nothing is asked for after the list read again."""
    eob = "eob " + REFUSED[1]
    again = [eob] if refusal.get("status") in (401, 403) or refusal.get("noauth") else []
    return ["list", eob] + again + ["list"]


# -- one EOB -----------------------------------------------------------------

@pytest.mark.parametrize("how", sorted(REFUSALS))
def test_an_eob_refused_while_the_list_still_reads_fails_alone(monkeypatch, tmp_path, caplog, how):
    signed_in(monkeypatch)
    page = Refuses(rows(), REFUSALS[how])
    out = tmp_path / "eob.pdf"
    with caplog.at_level(logging.INFO):
        assert site.download_document(page, doc_id(), out) is False
    assert not out.exists()
    assert page.calls == asked(REFUSALS[how])
    assert "refused while the list still reads" in caplog.text
    assert PAGE_WORDS.decode() not in caplog.text and REFUSED[0] not in caplog.text


@pytest.mark.parametrize("list_answer", [{"status": 401}, {"status": 403}, {"status": 200, "html": True}],
                         ids=["401", "403", "sign-in page"])
@pytest.mark.parametrize("how", sorted(REFUSALS))
def test_an_eob_refused_and_a_list_refused_after_it_is_a_sign_out(monkeypatch, tmp_path, how,
                                                                  list_answer):
    signed_in(monkeypatch)
    page = Refuses(rows(), REFUSALS[how], signs_out=list_answer)
    out = tmp_path / "eob.pdf"
    with pytest.raises(site.SessionExpired):
        site.download_document(page, doc_id(), out)
    assert not out.exists()
    # A refused list is asked once more with the session's headers taken
    # again, and the EOB is never asked for again.
    again = ["list"] if list_answer["status"] in (401, 403) else []
    assert page.calls == asked(REFUSALS[how]) + again


def test_an_eob_refused_and_a_list_that_does_not_come_after_it_fails_alone(monkeypatch, tmp_path):
    """A list that answers neither the rows nor a refusal is a list that did
    not come, which fails one EOB in resolve_eob_id too, and a session that
    ended shows at the next EOB's own list."""
    signed_in(monkeypatch)
    page = Refuses(rows(), REFUSALS["403"], signs_out={"status": 500})
    out = tmp_path / "eob.pdf"
    assert site.download_document(page, doc_id(), out) is False
    assert not out.exists()
    assert page.calls == asked(REFUSALS["403"])


def test_the_next_eob_is_taken_after_one_was_refused(monkeypatch, tmp_path):
    signed_in(monkeypatch)
    page = Refuses(rows(), REFUSALS["sign-in page"])
    assert site.download_document(page, doc_id(), tmp_path / "refused.pdf") is False
    out = tmp_path / "next.pdf"
    assert site.download_document(page, doc_id(CLAIMS[2]), out) is True
    assert out.read_bytes() == b"%PDF-1.4 invented"


# -- the run -----------------------------------------------------------------

@pytest.fixture
def run(tmp_path, monkeypatch):
    """The app's own Discover of the three claims, then its downloads, on a
    page that answers the refused claim's EOB as given."""
    signed_in(monkeypatch)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")

    def ran(page, capsys):
        app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), "--discover"]))
        app.page = lambda: page
        app._on_its_site = lambda: page
        app.check_session = lambda *_a, **_kw: None
        app.cmd_discover(quiet=True)
        capsys.readouterr()
        ended = None
        try:
            app.process(app._select())
        except SystemExit as e:
            ended = e
        return app, ended, capsys.readouterr().out
    return ran


def states(app) -> dict:
    return {k: v.get("state") for k, v in app.progress.data.items()}


def test_one_eob_refused_while_the_list_reads_fails_alone_and_the_rest_are_saved(run, capsys):
    """The refused EOB stopped the run before, so the EOBs after it were
    never asked for, and every later run stopped at it again."""
    page = Refuses(rows(), REFUSALS["403"], pdf=testkit.text_pdf(["Anthem made-up EOB"]))
    app, ended, said = run(page, capsys)
    assert ended is None, said
    assert states(app) == {"id:" + doc_id(c): ("Failed" if c == REFUSED else "Completed")
                           for c in CLAIMS}
    assert (app.stats["failed"], len(app.stats["new_files"])) == (1, 2)
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    assert "session has expired" not in said
    assert page.calls.count("eob " + REFUSED[1]) == 2
    assert not app.stats.get("session_expired")


def test_one_eob_refused_and_the_list_after_it_stop_the_run_as_signed_out(run, capsys):
    page = Refuses(rows(), REFUSALS["403"], signs_out={"status": 401},
                   pdf=testkit.text_pdf(["Anthem made-up EOB"]))
    app, ended, said = run(page, capsys)
    assert isinstance(ended, SystemExit), said
    assert "session has expired" in said
    assert "id:" + doc_id() not in app.progress.data
    assert "Nothing was saved" not in said
    # Nothing is asked for once the list was refused.
    assert page.calls[page.calls.index("eob " + REFUSED[1]):] == [
        "eob " + REFUSED[1], "eob " + REFUSED[1], "list", "list"]
