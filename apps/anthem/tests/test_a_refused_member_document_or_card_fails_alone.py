"""One member document or ID card Anthem refuses on its own fails alone,
and only its list refused after it is a sign-out.

Anthem's member documents and ID cards are saved in one loop of their own
(App._save_collected), after the EOBs. A 401, a 403 or a sign-in page where
one of them should be was read as a sign-out, which ended that surface's
pass, so every run ended it at the same document and the ones after it were
never taken. Now the surface's own list is read again with the call that
proves a session (paperpull_core.refused). A list refused too ends the
surface as signed out, as before. A list that did not come, a 500, a
timeout or one that holds nothing, says neither, and ends the surface as
its list does when it will not open, with nothing recorded against the
document. A list that still reads leaves that document failed with nothing
saved, the surface goes on, and the next run tries it again. The document is
never asked for twice.

The lists and the refusals are read by Anthem's own code, from a page that
answers each call in the shape Anthem does. Every name, period and word here
is invented.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core import testkit  # noqa: E402

site = app_mod.site

PAGE_WORDS = "made-up page words 4417"


def period(year: int) -> str:
    return "79DM-%d0101-%d1231-MED-000000A00A" % (year, year)


YEARS = (2026, 2025, 2024)
GIVEN = ("JANE", "JOHN", "JUNE")

LISTS = {
    "member documents": {"status": 200, "rows": [
        {"coverageKey": period(y), "documentType": "SBC"} for y in YEARS]},
    "ID cards": {"status": 200, "body": {"result": {"data": {"patient": [
        {"name": {"given": [given], "family": "DOE"},
         "healthIdentificationCard": [{"cardType": "normal", "effectiveDate": "2025-01-01"}]}
        for given in GIVEN]}}}},
}
EMPTY = {
    "member documents": {"status": 200, "rows": []},
    "ID cards": {"status": 200, "body": {"result": {"data": {"patient": []}}}},
}

# Each surface's documents in the order its list gives them, by the key the
# run records each under, and the one Anthem refuses.
KEYS = {
    "member documents": [site.member_doc_key(period(y), "SBC") for y in YEARS],
    "ID cards": [site.idcard_key("%s Doe:0" % g.title(), "normal") for g in GIVEN],
}
REFUSED = {"member documents": KEYS["member documents"][1], "ID cards": KEYS["ID cards"][1]}
COMMAND = {"member documents": "cmd_documents", "ID cards": "cmd_id_cards"}

# What one document can be answered with that reads as a sign-out.
REFUSALS = {
    "401": {"status": 401},
    "403": {"status": 403},
    "no session headers": {"noauth": True},
}


class Surfaces:
    """Answers a surface's list with its rows, and each read of it after the
    first with `again`, or raises `again` when it is an exception. Answers
    each document with a PDF, or a card with its picture, except the refused
    one's, which it answers as `refusal` says. Notes every call in order."""

    url = "https://membersecure.anthem.com/member/documents"

    def __init__(self, surface, refusal, again=None):
        self.surface, self.refusal, self.again = surface, refusal, again
        self.calls, self.lists = [], 0

    def evaluate(self, js, arg=None):
        if js in (site._MEMBER_DOCS_LIST_JS, site._IDCARD_LIST_JS):
            self.calls.append("list")
            self.lists += 1
            if self.lists > 1 and self.again is not None:
                if isinstance(self.again, BaseException):
                    raise self.again
                return json.loads(json.dumps(self.again))
            return json.loads(json.dumps(LISTS[self.surface]))
        if isinstance(arg, dict) and "coverageKey" in arg:
            key = site.member_doc_key(arg["coverageKey"], arg["documentType"])
            self.calls.append(key)
            if key == REFUSED[self.surface]:
                return dict(self.refusal)
            pdf = testkit.text_pdf(["the made-up document " + arg["coverageKey"]])
            return {"status": 200, "b64": base64.b64encode(pdf).decode()}
        if isinstance(arg, dict) and "patientKey" in arg:
            key = site.idcard_key(arg["patientKey"].title() + ":%d" % arg["ordinal"], arg["cardType"])
            self.calls.append(key)
            if key == REFUSED[self.surface]:
                return dict(self.refusal)
            return {"status": 200, "front": "aW52ZW50ZWQ=", "frontMime": "image/png"}
        raise AssertionError("an unexpected call into the page")


@pytest.fixture
def run(tmp_path, monkeypatch):
    """The app's own command for one surface, on a page that answers as
    given, with the session's capture stood in."""
    monkeypatch.setattr(site, "is_anthem_owned_page", lambda page: True)
    monkeypatch.setattr(site, "_prime_bucket", lambda *_a, **_kw: True)
    monkeypatch.setattr(site, "render_html_to_pdf",
                        lambda _page, html: testkit.text_pdf(["a made-up card"]))
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")

    def ran(page, capsys):
        app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg)]))
        app._on_its_site = lambda: page
        app.check_session = lambda *_a, **_kw: None
        capsys.readouterr()
        getattr(app, COMMAND[page.surface])()
        return app, capsys.readouterr().out
    return ran


def states(app) -> dict:
    return {k: v.get("state") for k, v in app.progress.data.items()}


SURFACES = sorted(LISTS)


@pytest.mark.parametrize("how", sorted(REFUSALS))
@pytest.mark.parametrize("surface", SURFACES)
def test_one_refused_while_its_list_still_reads_fails_alone_and_the_rest_are_saved(
        run, capsys, surface, how):
    """The refusal ended the surface before, so the documents after it were
    never asked for, and every later run ended it there again."""
    page = Surfaces(surface, REFUSALS[how])
    app, said = run(page, capsys)
    first, refused, last = KEYS[surface]
    assert states(app) == {first: "Completed", refused: "Failed", last: "Completed"}
    assert app.progress.data[refused]["notes"] == "Refused while its list still reads"
    assert app.stats["failed"] == 1 and len(app.stats["new_files"]) == 2
    assert not app.stats.get("session_expired")
    assert "session expired" not in said
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    # The list is read again once, and the refused one is never asked again.
    assert page.calls == ["list", first, refused, "list", last]


@pytest.mark.parametrize("list_answer", [{"status": 401}, {"status": 403}, {"noauth": True}],
                         ids=["401", "403", "no session headers"])
@pytest.mark.parametrize("surface", SURFACES)
def test_one_refused_and_its_list_refused_after_it_end_the_surface_as_signed_out(
        run, capsys, surface, list_answer):
    page = Surfaces(surface, REFUSALS["403"], again=list_answer)
    app, said = run(page, capsys)
    first, refused, _last = KEYS[surface]
    assert app.stats.get("session_expired") == 1
    assert "session expired" in said
    assert refused not in app.progress.data and states(app) == {first: "Completed"}
    assert "Nothing was saved" not in said
    assert page.calls == ["list", first, refused, "list"]


UNREAD = {
    "500": {"status": 500},
    "429": {"status": 429},
    "timeout": TimeoutError("Timeout 30000ms exceeded on made-up-host 4417"),
    "empty": None,
}


@pytest.mark.parametrize("list_answer", sorted(UNREAD))
@pytest.mark.parametrize("surface", SURFACES)
def test_one_refused_and_a_list_that_does_not_come_end_the_surface_as_unread(
        run, capsys, caplog, surface, list_answer):
    """Neither a sign-out nor that document's own failure. The surface ends
    as it does when its list will not open, counted as a failure so the run
    does not end clean, with nothing recorded against the document, and the
    next run takes it."""
    again = UNREAD[list_answer] if list_answer != "empty" else EMPTY[surface]
    page = Surfaces(surface, REFUSALS["403"], again=again)
    app, said = run(page, capsys)
    first, refused, _last = KEYS[surface]
    assert not app.stats.get("session_expired")
    assert "session expired" not in said
    assert "list could not be read again after one was refused" in said
    assert app.stats["failed"] == 1
    assert refused not in app.progress.data and states(app) == {first: "Completed"}
    assert "Nothing was saved" not in said
    assert page.calls == ["list", first, refused, "list"]
    assert "4417" not in said and "4417" not in caplog.text


def test_letters_and_claims_summaries_hand_no_list_on():
    """They are made here from what their lists carry and never refused, so
    their loop has no list to read again."""
    import inspect
    for name in ("cmd_letters", "cmd_claims_summaries"):
        assert "list_fn" not in inspect.getsource(getattr(app_mod.App, name)), name
    for name in ("cmd_documents", "cmd_id_cards"):
        assert "list_fn=site.list_" in inspect.getsource(getattr(app_mod.App, name)), name
