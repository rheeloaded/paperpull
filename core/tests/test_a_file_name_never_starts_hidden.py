"""A file's name never starts with a dot or a space.

A naming pattern can start with any field, and American Family's account is
its masked number, "...1234". A folder a pattern makes of it was "1234"
already, since each folder is made safe at both ends (storage._folder_name),
but the file's own name kept the dots. So the pattern
"{account} {date:yyyy-mm-dd} {kind}" named a statement
"...1234 2026-01-15 Statement.pdf", which a Mac, Linux and the share of
PaperPull Server hide, and the panel's zip of what was set aside leaves out.

So the leading run of dots and spaces comes off a file's own name where
every name is made (storage.file_name_of). The File names page, a download
and Rename then give the same name. sanitize_component is not where it
happens, since it builds the keys of most apps' records, and a key that
changed would make every such document look new and fetch it again. Names
the core and the apps hide on purpose while a file is on its way in never
pass through file_name_of, and stay hidden.

Every name, number and account here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import naming, storage  # noqa: E402
from paperpull_core.models import State  # noqa: E402
from paperpull_core.spec import AppSpec, DOCUMENT, Folder, INFRASTRUCTURE_FOLDERS  # noqa: E402

import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402

PATTERN = "{account} {date:yyyy-mm-dd} {kind}"
RECORD = {"account": "...1234", "category": "Statement", "date": "2026-01-15",
          "summary": "Statement ...1234"}
SHOWN = "1234 2026-01-15 Statement.pdf"
HIDDEN = "...1234 2026-01-15 Statement.pdf"


@pytest.fixture
def amfam(tmp_path, monkeypatch):
    """The core bound the way American Family binds it, with no pattern
    saved, put back after."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    spec = AppSpec(provider="American Family", project_dir=tmp_path, kind=DOCUMENT,
                   folders=[Folder("statements", "Statements"), *INFRASTRUCTURE_FOLDERS],
                   default_route="statements")
    storage.bind(spec)
    storage.set_filename_patterns({})
    return spec


def named(pattern=PATTERN, summary="Statement ...1234", **record):
    return storage.build_pdf_filename("2026-01-15", summary, "",
                                      record=dict(RECORD, **record), pattern=pattern)


def test_a_masked_account_never_starts_a_hidden_file_name(amfam):
    """N7-1. At 40491dd7 the name was "...1234 2026-01-15 Statement.pdf"."""
    assert naming.check(PATTERN) is None
    name = named()
    assert str(name) == SHOWN
    assert name.folder == ""


def test_the_preview_a_download_and_a_free_name_agree(amfam, tmp_path):
    """N7-3. The File names page, the name a run builds and the name
    unique_path files it under are one name, so the page shows what a
    download saves and Rename finds every file named already."""
    shown = naming.preview(PATTERN, RECORD, provider="American Family")
    built = named()
    folder = tmp_path / "Statements"
    folder.mkdir()
    filed = storage.unique_path(folder, built, 240)
    assert shown == str(built) == filed.name == SHOWN


def test_a_folder_of_the_same_account_was_never_hidden_and_stays_as_it_was(amfam):
    name = named("{account}/{date:yyyy-mm-dd} {summary}")
    assert name.folder == "1234"
    assert str(name) == "2026-01-15 Statement ...1234.pdf"


@pytest.mark.parametrize("text,kept", [
    ("...1234", "...1234"), (".hidden", ".hidden"), (" . x", ". x"), ("..", "Unnamed"),
    (". .1234", ". .1234"), ("...CON", "...CON"),
])
def test_sanitize_component_keeps_its_leading_dots(text, kept):
    """N7-4. It builds record keys, so its answer for each of these is what
    40491dd7 gave."""
    assert storage.sanitize_component(text) == kept


# The keys each app gives a statement of account "...1234", as 40491dd7
# builds them. A change to sanitize_component would change them, and every
# such statement would be fetched again beside its copy.
KEYS = {
    "amfam": "Statement:2026-01-15:Account Statement:...1234",
    "amazonvisa": "Statement:2026-01-15:...1234:Account Statement",
    "direkt1822": "Statement:2026-01-15:...1234:Account Statement",
    "dkb": "Statement:2026-01-15:...1234:Account Statement",
}


@pytest.mark.parametrize("app", sorted(KEYS))
def test_a_key_built_from_a_masked_account_is_as_it_was(app, monkeypatch):
    """N7-4."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    mod = census.load(census.REPO / "apps" / app)
    doc = mod.Document(title="Account Statement", category="Statement", summary="Statement",
                       date="2026-01-15", account="...1234")
    assert doc.key == KEYS[app]


def test_dots_inside_a_name_stay(amfam):
    """N7-5. Only the dots a name starts with come off."""
    assert str(named("{date:yyyy-mm-dd} {summary}")) == "2026-01-15 Statement ...1234.pdf"
    assert str(named("{date:yyyy-mm-dd} {summary}", summary="Plan v2.1 ...")) == \
        "2026-01-15 Plan V2.1.pdf"


# The default pattern's names, as 40491dd7 gives them, for statements whose
# summaries hold dots and spaces in every place but the start of a name.
DEFAULT_NAMES = [
    ("Statement ...1234", "2026-01-15 American Family Statement ...1234.pdf"),
    ("...1234 Statement", "2026-01-15 American Family ...1234 Statement.pdf"),
    ("Auto Policy v2.0", "2026-01-15 American Family Auto Policy V2.0.pdf"),
    ("Bill. . .", "2026-01-15 American Family Bill.pdf"),
    ("", "2026-01-15 American Family Purchase.pdf"),
]


@pytest.mark.parametrize("summary,expected", DEFAULT_NAMES)
def test_the_default_names_are_as_they_were(amfam, summary, expected):
    """N7-5."""
    assert storage.build_pdf_filename("2026-01-15", summary, "",
                                      record=dict(RECORD, summary=summary)) == expected


@pytest.mark.parametrize("account,expected", [
    ("...", "Unnamed.pdf"),
    (". .1234", "1234.pdf"),
    (".hidden", "hidden.pdf"),
    (" . x", "x.pdf"),
    ("...CON", "CON File.pdf"),
    ("...1234.", "1234.pdf"),
])
def test_a_name_of_dots_alone_is_unnamed_as_before(amfam, account, expected):
    """N7-7. A name of dots alone is "Unnamed" as it always was, and a name
    left as a device name once its dots are off is made safe as any other
    is, since Windows will not hold a file called CON."""
    assert str(named("{account}", account=account)) == expected


def test_two_statements_wanting_one_name_are_told_apart_and_neither_hidden(amfam, tmp_path):
    """N7-8."""
    folder = tmp_path / "Statements"
    folder.mkdir()
    first = storage.unique_path(folder, named(), 240, distinguisher="...0001")
    first.write_bytes(b"%PDF-1.4 first")
    second = storage.unique_path(folder, named(), 240, distinguisher="...0002")
    second.write_bytes(b"%PDF-1.4 second")
    third = storage.unique_path(folder, named(), 240)
    assert first.name == SHOWN
    assert second.name == "1234 2026-01-15 Statement 0002.pdf"
    assert third.name == "1234 2026-01-15 Statement (2).pdf"


def test_a_name_hidden_on_purpose_while_a_file_comes_in_stays_hidden(tmp_path):
    """The staging names the core and the apps make never pass through
    file_name_of, and unique_path leaves a name's start as it is."""
    for name in (".112-7124528-1.pdf.delivering", ".2026-01-15 Statement.pdf.moving"):
        assert storage.unique_path(tmp_path, name, 240).name == name


# -- Rename over an archive named the 40491dd7 way ------------------------------

AMFAM = census.REPO / "apps" / "amfam"


@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    return census.Home(AMFAM, tmp_path, monkeypatch, capsys)


def test_rename_brings_a_hidden_name_into_view_and_only_that_one(home):
    """N7-6. Two statements under the pattern, the first saved at 40491dd7
    under the hidden name, the second with no account, so its name started
    with the date then too. Rename offers the first alone, and after it the
    record and the row name the new file and a second Rename finds
    nothing to do."""
    home.set_pattern(PATTERN)
    app = home.build()
    doc = home.mod.Document(title="Account Statement", category="Statement",
                            summary="Statement ...1234", date="2026-01-15", account="...1234")
    listed = doc.to_dict()
    listed["state"] = State.DISCOVERED.value
    app.discovery.update(doc.key, listed, save=False)
    old = app.paths.statements / HIDDEN
    old.write_bytes(census.body_of("1234"))
    doc.pdf_path, doc.pdf_filename = str(old), old.name
    doc.downloaded_ok = True
    app._record(doc, State.COMPLETED)
    app._write_row(doc, "Downloaded", State.COMPLETED.value)
    other = home.mod.Document(title="Account Statement", category="Statement",
                              summary="Statement", date="2026-02-15", account="")
    kept = census.downloaded(app, other, census.body_of("none"))
    assert kept.name == "2026-02-15 Statement.pdf"
    census.saved(app)

    said = home.rename()
    assert "1 file(s) would be renamed." in said, said
    assert "%s -> %s" % (HIDDEN, SHOWN) in said, said

    said = home.rename("--apply")
    assert "Renamed 1 file(s)." in said, said
    files = home.files()
    assert files[census.body_of("1234")] == app.paths.statements / SHOWN
    assert files[census.body_of("none")] == kept
    app = home.build()
    [row] = [r for r in app.index_csv.read_all() if r["Document Date"] == "2026-01-15"]
    assert row["PDF Filename"] == SHOWN
    assert Path(row["PDF Full Path"]) == app.paths.statements / SHOWN
    assert Path(app.progress.get(doc.key)["pdf_path"]) == app.paths.statements / SHOWN
    assert census.NAMED_ALREADY in home.rename()


def test_a_hidden_name_in_manual_review_comes_into_view_when_a_row_names_it(home):
    """A statement put aside for review at 40491dd7 under the hidden name,
    its row saying so. Manual Review is a folder Rename files in, the name
    alone, so the file comes out of hiding in Manual Review and stays
    there."""
    home.set_pattern(PATTERN)
    app = home.build()
    doc = home.mod.Document(title="Account Statement", category="Statement",
                            summary="Statement ...1234", date="2026-01-15", account="...1234")
    listed = doc.to_dict()
    listed["state"] = State.DISCOVERED.value
    app.discovery.update(doc.key, listed, save=False)
    app.paths.manual_review.mkdir(parents=True, exist_ok=True)
    old = app.paths.manual_review / HIDDEN
    old.write_bytes(census.body_of("1234"))
    doc.pdf_path, doc.pdf_filename = str(old), old.name
    app._record(doc, State.NEEDS_MANUAL_REVIEW)
    app._write_row(doc, "Validation failed", "Needs Manual Review")
    census.saved(app)
    said = home.rename("--apply")
    assert "Renamed 1 file(s)." in said, said
    assert home.files()[census.body_of("1234")] == app.paths.manual_review / SHOWN
