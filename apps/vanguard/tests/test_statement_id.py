"""The id Vanguard's statements API gives a statement is not kept, for now.

The statements API answers each statement with a statementId. The listing
hands it over as statement_id, which the record does not read, so every
record keeps document_id empty. A download puts the end of a record's id
in a file's name when another file has the name, and a File names
pattern's {number} is the whole id. Nobody here has a Vanguard account,
so whether the id stays the same from one listing to the next, and ends
differently for each statement, has not been seen. Until it has, a second
statement wanting a name another file has is told apart by " (2)", as in
every app that keeps no id, and these tests say so, so that keeping the id
is a change made on purpose.

Each test runs Vanguard's own Discover and its own download_one up to the
moment it asks unique_path for a name. Stood in are the page's answer to
the statements API, the page itself, ensure_statements and the session
check. Every account and id is invented."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vanguard_docs as docs
import vanguard_site as site
from paperpull_core import storage as core_storage

QUARTER = "2026-06-30"
# A File names pattern without the summary, under which two accounts'
# statements of one quarter want one name.
NO_SUMMARY = "{date:yyyy-mm-dd} {provider}"


def statement(account: str, sid: str) -> dict:
    """One statement as the statements API answers it."""
    return {"accountId": "12340000000" + account[-4:], "accountNumber": account,
            "statementDescription": "Example Holder - Brokerage Account - %s" % account,
            "endDate": QUARTER, "processDate": QUARTER, "frequencyType": "QUARTERLY",
            "statementType": "ACCOUNT_GROUP", "statementId": sid}


ANSWER = [statement("11110001", "AAAAAAAAqRsT=="), statement("22220002", "BBBBBBBBxYzW==")]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Vanguard built from a config of its own, with the page's answer to
    the statements API stood in and no browser to reach for."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    app_dir = Path(docs.__file__).resolve().parent
    config = json.loads((app_dir / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0,
                   "default_start_date": "", "filename_pattern": NO_SUMMARY})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "collect_statements_json",
                        lambda page, years=None, keep=None: [dict(s) for s in ANSWER])

    def build():
        app = docs.App(docs.build_parser().parse_args(["--config", str(cfg)]))
        app.page = lambda: SimpleNamespace(url=site.URLS["documents"])
        app.check_session = lambda *_a, **_kw: None
        return app
    return build


class Saving(BaseException):
    """Where download_one asked unique_path to save, raised at that moment
    so no page is reached."""


def where_its_download_saves(app, doc) -> Path:
    name = core_storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)

    def asked(*args, **kwargs):
        raise Saving(core_storage.unique_path(*args, **kwargs))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(docs, "unique_path", asked)
        try:
            app.download_one(None, doc, name)
        except Saving as saving:
            return Path(str(saving))
    raise AssertionError("download_one saved the statement nowhere")


def listed(home):
    """Each statement as Vanguard's own Discover writes it down, by the id
    the API gave it."""
    app = home()
    app.cmd_discover(quiet=True)
    by_account = {rec["account"][-8:]: rec for rec in app.discovery.data.values()}
    return app, {s["statementId"]: by_account[s["accountNumber"]] for s in ANSWER}


def test_the_id_the_statements_api_gives_is_not_kept(home):
    _app, records = listed(home)
    assert len(records) == len(ANSWER)
    assert [rec.get("document_id") for rec in records.values()] == ["", ""]


def test_a_second_statement_wanting_a_taken_name_is_told_apart_by_its_place(home):
    app, records = listed(home)
    first, second = (docs.Document.from_dict(records[s["statementId"]]) for s in ANSWER)
    path = where_its_download_saves(app, first)
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    told = where_its_download_saves(app, second)
    assert told.name == "%s Vanguard (2).pdf" % QUARTER, told.name
