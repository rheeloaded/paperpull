"""The sample archive.

A folder of invented documents that ships with the program, so the Status
tab and both spreadsheets can be seen working without an account anywhere.
It is a mode this process is in, not a saved setting, and while it is on
nothing may be downloaded, created, renamed or removed.

The endpoints are called directly rather than through a test client, the
way the rest of this suite does it.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """A private settings file, so the sample is built under tmp_path and
    nothing here touches the real one, and the mode is always off after."""
    monkeypatch.setattr(app_module, "_settings_path", lambda: tmp_path / "cfg" / "settings.json")
    monkeypatch.delenv("APPS_ROOT", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    yield tmp_path
    app_module._SAMPLE = None


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _sample(on):
    return asyncio.run(app_module.api_sample(_Req({"on": on})))


def test_turning_it_on_builds_the_archive_somewhere_writable(panel):
    """Never inside the install. An upgrade replaces that, macOS will not
    let anything write into it, and spreadsheets get built into this."""
    out = _sample(True)
    dest = Path(out["root"])
    assert out["sample"] is True
    assert dest == app_module._sample_dest()
    assert not dest.is_relative_to(Path(app_module.__file__).resolve().parent)
    assert (dest / "README.txt").is_file()
    assert out["apps"] >= 3
    assert list(dest.rglob("*.pdf")), "the transactions workbook is built from PDFs"


def test_the_panel_reads_the_sample_while_it_is_on(panel):
    _sample(True)
    assert app_module.apps_root() == app_module._sample_dest()
    assert app_module.root_source() == "sample"


def test_it_beats_every_other_source_of_a_root(panel, tmp_path, monkeypatch):
    """Including the environment override, or asking to see the sample on a
    machine that has APPS_ROOT set would quietly do nothing."""
    app_module._settings_path().parent.mkdir(parents=True)
    app_module._settings_path().write_text(json.dumps({"apps_root": str(tmp_path / "saved")}), encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "env"))
    _sample(True)
    assert app_module.apps_root() == app_module._sample_dest()


def test_leaving_puts_the_old_root_back_untouched(panel, tmp_path):
    """Looking at the sample must not cost somebody the folder they chose,
    so the settings file is never written to."""
    cfg = app_module._settings_path()
    cfg.parent.mkdir(parents=True)
    mine = tmp_path / "mine"
    mine.mkdir()
    cfg.write_text(json.dumps({"apps_root": str(mine)}), encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    _sample(True)
    out = _sample(False)
    assert out["sample"] is False
    assert app_module.apps_root() == mine
    assert app_module.root_source() == "settings"
    assert cfg.read_text(encoding="utf-8") == before


def test_a_second_visit_reuses_the_copy_rather_than_rewriting_it(panel):
    """Anything built into the sample stays there between visits."""
    dest = Path(_sample(True)["root"])
    built = dest / "All Transactions.xlsx"
    built.write_text("built here", encoding="utf-8")
    _sample(False)
    _sample(True)
    assert built.read_text(encoding="utf-8") == "built here"


def test_a_half_copied_sample_is_replaced(panel):
    """A copy interrupted partway has no README, and would otherwise be
    used forever as if it were complete."""
    dest = app_module._sample_dest()
    dest.mkdir(parents=True)
    (dest / "junk.txt").write_text("leftover", encoding="utf-8")
    _sample(True)
    assert (dest / "README.txt").is_file()
    assert not (dest / "junk.txt").exists()


def test_the_sample_is_never_filled_with_real_app_code(panel, monkeypatch, tmp_path):
    """Its folders are named after providers and its entry scripts are
    stubs, so the every-run code refresh would match them to the templates
    and overwrite them, leaving a Backups folder in the sample as well."""
    tmpl = tmp_path / "templates"
    (tmpl / "chase").mkdir(parents=True)
    (tmpl / "chase" / "chase_docs.py").write_text("the real thing", encoding="utf-8")
    monkeypatch.setattr(app_module, "_templates_root", lambda: tmpl)
    _sample(True)
    assert app_module.refresh_installs(force=True) == {}
    stub = app_module._sample_dest() / "Chase Statements" / "chase_docs.py"
    assert "the real thing" not in stub.read_text(encoding="utf-8")
    assert not (app_module._sample_dest() / "Chase Statements" / "Backups").exists()


def test_nothing_can_be_run_while_looking_at_it(panel):
    _sample(True)
    why = app_module.setup_needed({"dir": str(app_module._sample_dest() / "Chase Statements")})
    assert "sample archive" in why
    assert "nothing to download" in why


def test_the_archive_cannot_be_changed_while_looking_at_it(panel):
    """Create, add a person, remove and change-the-root all write into the
    root, and the root is the sample."""
    _sample(True)
    with pytest.raises(fastapi.HTTPException) as e:
        app_module._not_in_sample()
    assert e.value.status_code == 409
    _sample(False)
    assert app_module._not_in_sample() is None


def test_a_build_that_shipped_no_sample_says_so(panel, monkeypatch):
    monkeypatch.setattr(app_module, "_sample_builder", lambda: None)
    with pytest.raises(fastapi.HTTPException) as e:
        _sample(True)
    assert e.value.status_code == 500


# -- what gets built -----------------------------------------------------------

def _pdf_text(pdf: Path) -> str:
    """The page's text, straight out of the one compressed stream these are
    written with. Enough to read them without a PDF library."""
    import re
    import zlib
    body = pdf.read_bytes().split(b"stream\n", 1)[1].rsplit(b"\nendstream", 1)[0]
    return " ".join(m.decode("latin-1") for m in re.findall(rb"\((.*?)\) Tj", zlib.decompress(body)))


def test_what_gets_built_is_an_archive_the_panel_can_read(panel):
    """It has to look like installs, or somebody who clicks See a sample
    archive lands back on the welcome screen."""
    dest = Path(_sample(True)["root"])
    assert app_module._looks_like_installs(dest) >= 3
    assert len(list(dest.rglob("*.pdf"))) >= 20
    assert list(dest.glob("*/*Order History.csv")), "the purchases workbook is built from these"
    assert list(dest.glob("*/progress.json")), "the Status tab is built from these"


def test_every_document_in_it_says_it_is_invented(panel):
    """Nobody should be able to mistake one of these for a real statement,
    including after it has been copied out of the folder and mailed to
    somebody."""
    dest = Path(_sample(True)["root"])
    pdfs = list(dest.rglob("*.pdf"))
    assert pdfs
    for pdf in pdfs:
        text = _pdf_text(pdf).lower()
        assert "sample document created by paperpull" in text, pdf
        assert "invented" in text, pdf


def test_it_is_built_the_same_way_every_time(panel, tmp_path):
    """A fixed seed, so two people looking at the sample are looking at the
    same numbers, and a rebuild after an upgrade is not a surprise."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mk", app_module._sample_builder())
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    a, b = tmp_path / "a", tmp_path / "b"
    mk.build(a)
    mk.build(b)
    names = lambda d: sorted(str(p.relative_to(d)) for p in d.rglob("*"))
    assert names(a) == names(b)
    assert (a / "Chase Statements" / "progress.json").read_bytes() ==            (b / "Chase Statements" / "progress.json").read_bytes()
