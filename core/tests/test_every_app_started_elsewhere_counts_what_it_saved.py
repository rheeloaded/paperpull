"""Every app started in another folder counts what it saved before exactly
as one started in its install does, and records the paths it would (#166).

Every launcher starts a run in the install's own folder, and a panel
install's config says "." for its output folder, so every path a run
records in progress.json and its index is relative to the install. 0.62.0
read such a folder from the config's folder for a run started anywhere
else, by writing the folder out in full. Such a run then recorded full
paths, and read a path recorded before from the folder it was started in,
where no file is. So a copy put aside for review, which counts as saved
only while its file is there and whole, was not found, and the run would
download it again.

A run started elsewhere now works in its config's folder, as a launcher's
run does. Each app here is built from its own code with a config in a
made-up install, as the census of test_every_app_renames_each_file_for_its_own_record
builds it, and two documents or purchases are saved by its own code. One
record names its file as a run in the install recorded it, and the other
by its full path, as a run started elsewhere recorded it from 0.62.0 to
0.65.0. The app started elsewhere has to decide about each exactly as the
app started in its install does, first with each a copy put aside for
review whose file is there, then with each saved for good and its file
deleted, which never downloads it again. What it would record for a
document it saves next has to read as what a run in its install records.
"""
import importlib.util
import os
from pathlib import Path

import pytest

from paperpull_core import storage as core_storage
from paperpull_core.models import State
from paperpull_core.testkit import sample_pdf


def _rename_census():
    path = Path(__file__).with_name("test_every_app_renames_each_file_for_its_own_record.py")
    spec = importlib.util.spec_from_file_location("rename_census_for_started_elsewhere", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _rename_census()
APPS, IDS = census.APPS, census.IDS


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return census.Home(request.param, tmp_path, monkeypatch, capsys)


def kind_of(home):
    return getattr(home.mod, "Document", None) or home.mod.Purchase


def saved_before(home, app) -> list:
    """Two documents or purchases saved by the app's own code, as a run
    started in the install saves them, each with a whole PDF. Their keys."""
    if hasattr(home.mod, "Document"):
        # Of two titles where the key is the date and the title alone.
        pair = census.two_documents(home) or census.two_documents(
            home, titles=("Monthly Statement - Checking", "Monthly Statement - Savings"))
        for doc in pair:
            census.downloaded(app, doc, sample_pdf())
        keys = [doc.key for doc in pair]
    else:
        numbers = ("ORD1111", "ORD2222")
        for number in numbers:
            census.purchased(home, app, number, sample_pdf())
        keys = [key for number in numbers for key, rec in app.progress.data.items()
                if isinstance(rec, dict) and rec.get("order_number") == number]
    census.saved(app)
    assert len(keys) == 2, keys
    return keys


def decisions(home, start: Path) -> dict:
    """Whether the app, started in `start`, counts each record as done."""
    os.chdir(start)
    app = home.build()
    kind = kind_of(home)
    return {key: app._already_done(kind.from_dict(rec))
            for key, rec in app.progress.data.items() if isinstance(rec, dict)}


def where_it_saves_next(home, start: Path) -> str:
    """The path the app, started in `start`, would save and record a
    document it has not saved yet at, as its own download names it, and
    the folder a purchase goes to for a receipt app."""
    os.chdir(start)
    app = home.build()
    if hasattr(home.mod, "Document"):
        doc = census.two_documents(home, titles=("Annual Summary - Checking",
                                                 "Annual Summary - Savings"),
                                   summary="Annual Summary")[0]
        name = core_storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
        return str(census.where_its_download_saves(app, doc, name))
    from paperpull_core.models import IN_STORE, ONLINE
    kind = next(k for k in (ONLINE, IN_STORE) if census.routes(app, k))
    return str(app.paths.folder_for(kind))


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_every_app_started_elsewhere_counts_what_it_saved_as_at_home(home, tmp_path,
                                                                     monkeypatch):
    install = tmp_path / "Example Install"
    install.mkdir()
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    home.config.update(output_dir=".", profile_dir="./browser-profile")
    home.cfg = install / "config.json"
    home._write_config()
    # Put back after, whichever folder a build left this process in.
    monkeypatch.chdir(install)

    app = home.build()
    keys = saved_before(home, app)
    files = [install / app.progress.get(key)["pdf_path"] for key in keys]
    assert all(f.is_file() for f in files), files
    assert not any(Path(app.progress.get(key)["pdf_path"]).is_absolute() for key in keys)
    app.progress.update(keys[1], {"pdf_path": os.path.normpath(files[1])}, save=False)
    for key in keys:
        app.progress.update(key, {"downloaded_ok": False,
                                  "state": State.NEEDS_MANUAL_REVIEW.value}, save=False)
    app.progress.save()

    at_home = decisions(home, install)
    assert at_home == {key: True for key in keys}, (
        "%s did not count a copy put aside for review, whose file is there, as saved"
        % home.app.name)
    assert decisions(home, elsewhere) == at_home, (
        "%s started elsewhere did not find a file a record names" % home.app.name)

    os.chdir(install)
    app = home.build()
    for key in keys:
        app.progress.update(key, {"downloaded_ok": True, "state": State.COMPLETED.value},
                            save=False)
    app.progress.save()
    for f in files:
        f.unlink()
    assert decisions(home, install) == {key: True for key in keys}
    assert decisions(home, elsewhere) == {key: True for key in keys}, (
        "%s started elsewhere would download again what it saved" % home.app.name)

    next_at_home = where_it_saves_next(home, install)
    assert not Path(next_at_home).is_absolute(), next_at_home
    assert where_it_saves_next(home, elsewhere) == next_at_home
    assert list(elsewhere.iterdir()) == [], "a run started elsewhere wrote there"
