"""Without kind folders (#201), the setting is refused unless a document's
name says which kind it is, for real.

Two kinds of one date and one summary share a folder once the folder of
their kind is gone. The usual names carry the kind in "[ {kind}]", but a
statements app passes no kind, so it renders empty for every one of them,
and a Statement and a Tax Document of one day were both
"2026-01-31 Testco Monthly.pdf", one of them " (2)" with nothing to say
which was which. So the setting is judged by whether a field of the
pattern is one a document's folder of its kind follows from. For a
statements app that is {kind}, its category, in a pattern somebody wrote.
For a receipts app it is {type}, its purchase type, and {kind} too when it
files invoices apart. An app that files a kind by name, as Anthem files ID
cards and letters, has no field that says it, and is refused whatever the
pattern says.

Every folder is a throwaway one under tmp_path, and every name is invented.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import storage  # noqa: E402
from paperpull_core.spec import (AppSpec, DOCUMENT, Folder, INFRASTRUCTURE_FOLDERS,  # noqa: E402
                                 RECEIPT)
from test_documents_folder import on_the_server, server, write  # noqa: E402,F401
from test_naming_folders import link_folder  # noqa: E402
from paperpull_core.storage import Paths  # noqa: E402


@pytest.fixture(autouse=True)
def no_pattern():
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def flat(tmp_path, pattern=None, **more):
    settings = {"output_dir": str(tmp_path / "out"), "documents_dir": str(tmp_path / "Watched"),
                "kind_folders": False, **more}
    if pattern is not None:
        settings["filename_pattern"] = pattern
    return storage.load_config(write(tmp_path / "app", settings))


def refused(tmp_path, pattern=None) -> str:
    with pytest.raises(SystemExit) as stop:
        flat(tmp_path, pattern)
    assert not (tmp_path / "out").exists() and not (tmp_path / "Watched").exists(), (
        "refused before anything is made")
    return str(stop.value)


# -- the collision the setting has to refuse ---------------------------------------------

def test_under_the_usual_names_two_kinds_of_one_day_want_one_name(tmp_path):
    """Why the usual names do not tell kinds apart for a statements app."""
    statement = storage.build_pdf_filename("2026-01-31", "Monthly", "",
                                           record={"category": "Statement"})
    other = storage.build_pdf_filename("2026-01-31", "Monthly", "",
                                       record={"category": "Tax Document"})
    assert str(statement) == str(other) == "2026-01-31 Testco Monthly.pdf"


def test_the_usual_names_are_refused_for_a_provider_of_several_kinds(tmp_path):
    said = refused(tmp_path)
    assert "Statements" in said and "Other Documents" in said and "{kind}" in said, said


def test_a_pattern_naming_the_kind_gives_two_kinds_of_one_day_two_names(tmp_path):
    flat(tmp_path, "{year}/{date} {summary} {kind}")
    statement = storage.build_pdf_filename("2026-01-31", "Monthly", "",
                                           record={"category": "Statement"})
    other = storage.build_pdf_filename("2026-01-31", "Monthly", "",
                                       record={"category": "Tax Document"})
    assert str(statement) != str(other)
    assert str(other) == "2026-01-31 Monthly Tax Document.pdf"


@pytest.mark.parametrize("pattern", ["{year}/{date} {summary} {kind}",
                                     "{kind}/{date} {summary}",
                                     "{date} {summary}[ {kind}]",
                                     "{date} {summary}[ - {kind}][ {account}]"])
def test_a_pattern_whose_kind_always_shows_is_taken(tmp_path, pattern):
    assert flat(tmp_path, pattern)["kind_folders"] is False


@pytest.mark.parametrize("pattern", ["{date} {summary}",
                                     "{date} {number|kind}",
                                     "{date} {summary}[ {account} {kind}]",
                                     "{date} {summary} {type}"])
def test_a_pattern_whose_kind_may_not_show_is_refused(tmp_path, pattern):
    """{number|kind} is the number when there is one, and an optional
    section with another field in it drops the kind with that field."""
    said = refused(tmp_path, pattern)
    assert "{kind}" in said, said


# -- what each app files ------------------------------------------------------------------

def by_name(project_dir) -> AppSpec:
    """Anthem's way, ID cards and letters filed in folders of their own by
    name, with one route for the rest."""
    return AppSpec(provider="Cardco", project_dir=project_dir, kind=DOCUMENT,
                   folders=[Folder("eobs", "EOBs"), Folder("id_cards", "ID Cards"),
                            Folder("letters", "Letters"), *INFRASTRUCTURE_FOLDERS],
                   routes={"Insurance Document": "eobs"}, default_route="eobs")


def test_an_app_filing_a_kind_by_name_is_refused_whatever_the_pattern(tmp_path):
    storage.bind(by_name(tmp_path))
    said = refused(tmp_path, "{kind}/{year}/{date} {summary} {kind}")
    assert "ID Cards" in said and "Letters" in said and "EOBs" in said, said


def shop(project_dir, invoices=False) -> AppSpec:
    folders = [Folder("online", "Online Purchases"), Folder("instore", "In-Store Purchases")]
    routes = {"Online": "online"}
    if invoices:
        folders.append(Folder("invoices", "Invoices"))
        routes["invoices"] = "invoices"
    return AppSpec(provider="Shopco", project_dir=project_dir, kind=RECEIPT,
                   folders=[*folders, *INFRASTRUCTURE_FOLDERS], routes=routes,
                   default_route="instore")


def test_a_receipts_app_needs_the_purchase_type(tmp_path):
    """Its kind is Receipt for an online and an in-store purchase alike."""
    storage.bind(shop(tmp_path))
    said = refused(tmp_path, "{date} {summary} {kind}")
    assert "{type}" in said and "Online Purchases" in said, said
    assert flat(tmp_path, "{type}/{date} {summary}")["kind_folders"] is False


def test_a_receipts_app_filing_invoices_apart_needs_the_kind_too(tmp_path):
    storage.bind(shop(tmp_path, invoices=True))
    said = refused(tmp_path, "{type}/{date} {summary}")
    assert "{kind}" in said and "Invoices" in said, said
    assert flat(tmp_path, "{type}/{date} {summary} {kind}")["kind_folders"] is False


def test_a_receipts_app_of_one_kind_needs_nothing(tmp_path):
    storage.bind(AppSpec(provider="Shopco", project_dir=tmp_path, kind=RECEIPT,
                         folders=[Folder("online", "Online Purchases"), *INFRASTRUCTURE_FOLDERS],
                         routes={"Online": "online"}, default_route="online"))
    assert flat(tmp_path)["kind_folders"] is False


# -- PaperPull Server, a link out below a documents folder without kind folders -----------

def test_on_the_server_a_link_out_in_a_patterns_folder_stops_the_run(server):  # noqa: F811
    """Without kind folders the pattern's folders are the first level of
    the documents folder, and its second level is where a run writes, so
    the start of a run walks it as it walks a folder of a kind."""
    outside = server.parent.parent / "elsewhere"
    outside.mkdir()
    docs = server.parent / "Documents"
    (docs / "2026").mkdir(parents=True)
    link_folder(outside, docs / "2026" / "Chase")
    settings = dict(documents_dir=str(docs), filename_pattern="{year}/{account}/{date} {kind}")
    storage.load_config(on_the_server(server, **settings))
    with pytest.raises(SystemExit) as stop:
        storage.load_config(on_the_server(server, kind_folders=False, **settings))
    assert "link" in str(stop.value)


# -- which earlier documents folders are filing folders ------------------------------------

def test_an_account_that_never_filed_without_kind_folders_has_mains_filing_folders(tmp_path):
    """A documents folder used before is a filing folder as a whole only
    once documents were filed in it without kind folders. Otherwise every
    file anywhere in it would count as the account's."""
    out, docs = tmp_path / "out", tmp_path / "Watched"
    paths = Paths(out, documents_dir=str(docs))
    paths.remember_documents()
    assert docs not in Paths(out, documents_dir=str(docs)).filing_folders()
    assert docs not in Paths(out, documents_dir="").filing_folders()
    flat_paths = Paths(out, documents_dir=str(docs), kind_folders=False)
    flat_paths.remember_documents()
    for later in (Paths(out, documents_dir=str(docs)), Paths(out, documents_dir="")):
        assert docs in later.filing_folders(), "documents filed there flat are still found"
