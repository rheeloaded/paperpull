"""Two accounts' statements of one day are each the first of their account.

Schwab keeps a document under its account, type, title and date, so a
Brokerage Statement of the same day in two accounts is two keys, and each is
the first, number 0, of its own. Up to 0.33 the site numbered them that way.
From 0.34 the numbers were handed out across accounts, so a record already
saved at 0 in the second account found 0 taken by the first, was numbered
again, and every such statement was downloaded a second time beside the one
already saved.

The provider is stood in: two accounts, one statement each on one day, and
a PDF for an id.
"""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import storage as core_storage
import schwab_docs as docs
import schwab_site as site

PAGE = SimpleNamespace(url="about:blank")
ACCOUNTS = [("11111111", "Brokerage"), ("22222222", "Example Trust")]


def pdf_of(document_id: str) -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "document %s" % document_id})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


class Schwab:
    def __init__(self, monkeypatch):
        self.ids = []
        self.asked = []
        monkeypatch.setattr(site, "ensure_statements", lambda page: True)
        monkeypatch.setattr(site, "_gateway_call", self._call)
        monkeypatch.setattr(site, "fetch_pdf", self._pdf)

    def _call(self, page, url, headers, post_body=None):
        if url == site.API["accounts"]:
            body = {"accountSelectorData": {"brokerageAccountList": {"brokerageAccounts": [
                {"id": acct, "nickName": nick} for acct, nick in ACCOUNTS]}}}
        else:
            body = {"documents": [
                {"documentId": "DOC" + acct[0], "documentName": "Brokerage Statement",
                 "type": site.TYPE_STATEMENTS, "onDemandDocumentType": "Statements",
                 "date": "07/31/2026", "accountDisplayName": acct[:4] + "-" + acct[4:]}
                for acct in self.ids]}
        return {"status": 200, "body": body}

    def _pdf(self, page, doc):
        self.asked.append(doc["documentId"])
        return 200, pdf_of(doc["documentId"])


def _home(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    config = json.loads((Path(docs.__file__).parent / "config.example.json")
                        .read_text(encoding="utf-8"))
    config.update({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(docs.App, "page", lambda app: PAGE)
    monkeypatch.setattr(docs.App, "_on_its_site", lambda app: PAGE)
    monkeypatch.setattr(docs.App, "check_session", lambda app, *_a, **_kw: None)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return cfg, Path(config["output_dir"])


def _as_saved_before_0_34(out: Path) -> None:
    """Every record numbered within its own account, as the site did."""
    for name in ("progress.json", "discovery.json"):
        path = out / name
        records = json.loads(path.read_text(encoding="utf-8"))
        rewritten = {}
        for key, record in records.items():
            record["occurrence"] = 0
            rewritten[key.split("#")[0]] = record
        path.write_text(json.dumps(rewritten), encoding="utf-8")


def test_a_statement_saved_first_in_each_account_is_not_downloaded_again(
        tmp_path, monkeypatch, capsys):
    cfg, out = _home(tmp_path, monkeypatch)
    provider = Schwab(monkeypatch)
    provider.ids = [acct for acct, _nick in ACCOUNTS]
    docs.main(["--config", str(cfg), "--all", "--yes"])
    assert sorted(provider.asked) == ["DOC1", "DOC2"]

    _as_saved_before_0_34(out)
    saved = json.loads((out / "progress.json").read_text(encoding="utf-8"))
    assert len(saved) == 2 and all(r["occurrence"] == 0 for r in saved.values())

    # The other way around too, so neither account is first by luck.
    provider.ids.reverse()
    provider.asked = []
    capsys.readouterr()
    docs.main(["--config", str(cfg), "--all", "--yes"])
    said = " ".join(capsys.readouterr().out.split())
    assert provider.asked == [], said
    assert len(list(out.rglob("*.pdf"))) == 2
