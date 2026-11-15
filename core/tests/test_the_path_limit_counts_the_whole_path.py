"""On Windows the path limit counts the whole path, as Windows does.

Every install's config has output_dir ".", so the folder of each kind is
the relative path "Statements", and max_path_length was measured against
that. Windows with long paths turned off counts the whole path against its
260 characters, from the drive, and a name a pattern filed three folders
deep passed the check at 240 and was 319 to 356 characters in full.

So on Windows the folder's whole path is measured, normalized as Windows
reads it (a second person's "../<install> - Robin" is not counted with its
".."), never through a link to where it leads, and in UTF-16 units, which
is what Windows counts. The three places that measure, the folders a
pattern names (filing_folder), the name itself (_free_name) and Rename's
question whether an ending fits whole (renaming._fits_whole), measure the
same way, so a download and Rename agree. A Mac and PaperPull Server have
no such limit, and there the relative path is measured as before, so not
one name changes on them.

Every name, number and account here is invented.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import storage  # noqa: E402
from paperpull_core.models import State  # noqa: E402
from paperpull_core.spec import AppSpec, DOCUMENT, Folder, INFRASTRUCTURE_FOLDERS  # noqa: E402

import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402
from test_naming_folders import _long_paths_work  # noqa: E402

WINDOWS_ONLY = "the whole path is measured on Windows only, where its 260-character limit is"
LONG_RECORD = {"account": "A" * 70, "store_info": "B" * 70, "purchase_type": "C" * 70}
THREE_FOLDERS = "{account}/{store}/{type}/{date:yyyy-mm-dd} {summary}"


def whole(path) -> int:
    """How long Windows counts a path, from the drive, in UTF-16 units."""
    return len(os.path.abspath(str(path)).encode("utf-16-le")) // 2


@pytest.fixture
def measured(monkeypatch):
    """Measure as Windows measures, or as a Mac and the Server do, on any
    system, so both rules are held wherever the suite runs."""
    def measure(whole_path: bool):
        monkeypatch.setattr(storage, "_WINDOWS_MEASURE", whole_path, raising=False)
    return measure


@pytest.fixture
def amfam(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    spec = AppSpec(provider="American Family", project_dir=tmp_path, kind=DOCUMENT,
                   folders=[Folder("statements", "Statements"), *INFRASTRUCTURE_FOLDERS],
                   default_route="statements")
    storage.bind(spec)
    storage.set_filename_patterns({})
    return spec


def installed(tmp_path, monkeypatch, name="amfam") -> Path:
    """An install's folder, where every launcher starts a run."""
    install = tmp_path / "PaperPull" / "apps" / name
    install.mkdir(parents=True)
    monkeypatch.chdir(install)
    return install


def test_the_path_limit_counts_the_whole_path(amfam, tmp_path, monkeypatch):
    """N8-1. At 40491dd7 the path was 240 characters as measured, from
    "Statements", and far past it in full."""
    if sys.platform != "win32":
        pytest.skip(WINDOWS_ONLY)
    installed(tmp_path, monkeypatch)
    folder = storage.Paths(Path("."), amfam, documents_dir="").folder_for("Statement")
    assert not folder.is_absolute()
    name = storage.build_pdf_filename("2026-03-31", "D" * 100, "", record=LONG_RECORD,
                                      pattern=THREE_FOLDERS)
    p = storage.unique_path(folder, name, 240)
    assert whole(p) <= 240, (len(str(p)), whole(p))


def relative_home(app: str, tmp_path, monkeypatch, capsys) -> census.Home:
    """An app as an install runs it, output_dir "." in a config beside it,
    started in the install's folder."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    home = census.Home(census.REPO / "apps" / app, tmp_path, monkeypatch, capsys)
    install = installed(tmp_path, monkeypatch, app)
    home.cfg = install / "config.json"
    home.config["output_dir"] = "."
    home._write_config()
    home.out = install
    return home


ACCOUNT = "Business Checking Operating Account for the Northwest Regional Office"
# Title cased already, as a name writes a summary.
SUMMARY = ("Business Statement for the Period Ending March With Detail of All Accounts "
           "and Every Transaction")


def test_a_download_into_an_installs_own_folder_keeps_to_the_limit_in_full(
        tmp_path, monkeypatch, capsys):
    """N8-2. Chase Business, through its own download, with the folders a
    long pattern names. At 40491dd7 the path it saved to was 240 characters
    from the install and far more in full."""
    if sys.platform != "win32":
        pytest.skip(WINDOWS_ONLY)
    home = relative_home("chasebusiness", tmp_path, monkeypatch, capsys)
    home.set_pattern("{account}/{kind}/{summary}/{date:yyyy-mm-dd} {summary}")
    app = home.build()
    assert not Path(app.paths.root).is_absolute()
    doc = home.mod.Document(title="Business Statement", category="Statement",
                            summary=SUMMARY, date="2026-03-31", account=ACCOUNT)
    name = storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    path = census.where_its_download_saves(app, doc, name)
    assert whole(path) <= 240, (len(str(path)), whole(path), str(path))


# -- measured the way Windows measures, on any system ----------------------------------

def test_a_second_persons_folder_is_measured_without_its_dots(amfam, tmp_path, monkeypatch,
                                                              measured):
    """N8-3. A second person's output_dir is "../<install> - Robin", as the
    panel writes it. Measured as written, from where the run starts, the
    ".." and the install's name counted for nothing and cut the name more
    than the path needs. Measured whole, a file there fits to the limit
    exactly as one in the same folder named in full."""
    measured(True)
    install = installed(tmp_path, monkeypatch)
    robin = install.parent / "amfam - Robin" / "Statements"
    robin.mkdir(parents=True)
    name = storage.build_pdf_filename("2026-03-31", "E" * 118, "")
    as_written = storage.unique_path(Path("../amfam - Robin/Statements"), name, 240)
    in_full = storage.unique_path(robin, name, 240)
    assert as_written.name == in_full.name
    if whole(robin) + 1 + len(name) > 240:
        assert whole(as_written) == whole(in_full) == 240
    first = storage.unique_path(Path("Statements"), name, 240)
    assert whole(first) <= 240 and first.name.startswith(in_full.stem)


def test_an_emoji_is_two_where_windows_counts_two(amfam, tmp_path, measured):
    """Windows counts a path in UTF-16 units, and an emoji is two of them,
    so a name of emoji is cut to the limit as Windows counts it. Counted in
    characters it passed the check and failed the write."""
    measured(True)
    folder = tmp_path / ("q" * max(1, 170 - whole(tmp_path) - 1))
    folder.mkdir()
    name = storage.build_pdf_filename("2026-03-31", "\U0001F389" * 60, "")
    p = storage.unique_path(folder, name, 240)
    assert 239 <= whole(p) <= 240, whole(p)
    assert len(os.path.abspath(p)) < whole(p)


def make_link(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_folder_reached_through_a_link_is_measured_as_it_is_reached(amfam, tmp_path,
                                                                    measured):
    """N8-3. A link is measured by its own path, which is what Windows
    counts, never by where it leads."""
    measured(True)
    target = tmp_path / ("t" * 90) / "Statements"
    target.mkdir(parents=True)
    link = tmp_path / "s"
    try:
        make_link(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system makes no link for an ordinary user")
    name = storage.build_pdf_filename("2026-03-31", "F" * 118, "")
    p = storage.unique_path(link, name, 240)
    assert p.parent == link
    assert whole(p) == min(240, whole(link) + 1 + len(name))


def test_a_folder_too_deep_in_full_says_so(amfam, tmp_path, monkeypatch, measured):
    """N8-6, from a relative folder. A folder whose whole path leaves no
    room for a name raises the ValueError naming max_path_length."""
    measured(True)
    deep = tmp_path / ("g" * max(1, 236 - whole(tmp_path) - 1))
    deep.mkdir()
    monkeypatch.chdir(deep)
    Path("Statements").mkdir()
    with pytest.raises(ValueError) as e:
        storage.unique_path(Path("Statements"), "2026-08-18 Statement.pdf", 240)
    assert "max_path_length" in str(e.value)


@pytest.mark.parametrize("whole_path", [True, False], ids=["windows", "mac-and-server"])
def test_a_download_and_rename_agree_under_a_deep_working_folder(
        tmp_path, monkeypatch, capsys, measured, whole_path):
    """N8-4. A document saved through the app's own download under a long
    pattern of three folders, the install deep enough that the folders fit
    only when the path is measured from the install. Rename finds it named
    already, whichever way the path is measured."""
    measured(whole_path)
    if not whole_path and sys.platform == "win32" and not _long_paths_work():
        pytest.skip("the folders a pattern names fit here only past 260 characters in full")
    deep = tmp_path / ("h" * max(1, 150 - whole(tmp_path) - 1))
    home = relative_home("amfam", deep, monkeypatch, capsys)
    home.set_pattern("{account}/{kind}/{summary}/{date:yyyy-mm-dd} {summary}")
    app = home.build()
    doc = home.mod.Document(title="Account Statement", category="Statement",
                            summary=SUMMARY, date="2026-03-31", account=ACCOUNT)
    path = census.downloaded(app, doc)
    census.saved(app)
    if whole_path:
        assert whole(path) <= 240, whole(path)
        assert path.parent == app.paths.statements, "the folders cannot fit in full"
    else:
        assert len(str(path)) <= 240
        assert path.parent != app.paths.statements, "the folders fit from the install"
    name = storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    assert storage.fitted_name(app.paths.statements, name, 240) == path.name
    assert census.NAMED_ALREADY in home.rename()


def saved_as(app, doc, name: str, body: bytes) -> Path:
    """A document as 40491dd7 saved it, under the name it gave."""
    listed = doc.to_dict()
    listed["state"] = State.DISCOVERED.value
    app.discovery.update(doc.key, listed, save=False)
    path = app.paths.statements / name
    path.write_bytes(body)
    doc.pdf_path, doc.pdf_filename = str(path), path.name
    doc.downloaded_ok = True
    app._record(doc, State.COMPLETED)
    app._write_row(doc, "Downloaded", State.COMPLETED.value)
    return path


@pytest.mark.parametrize("whole_path", [True, False], ids=["windows", "mac-and-server"])
def test_an_archive_named_the_old_way_is_offered_only_what_is_too_long_in_full(
        tmp_path, monkeypatch, capsys, measured, whole_path):
    """N8-5. Three statements saved at 40491dd7 under an install's own
    folder. Two fit in full and are offered nothing. The third's name is as
    long as makes its whole path 250 characters, which 40491dd7 measured
    from the install, far under the limit. On Windows it alone is offered,
    cut by the ten characters it is over, and on a Mac and the Server
    nothing is."""
    measured(whole_path)
    natural = whole(tmp_path) + len("/PaperPull/apps/amfam")
    if natural > 200:
        pytest.skip("the temporary folder is too deep to hold a path of 250 in full")
    # Deep enough that the long name is at most the 124 characters a name
    # had at 40491dd7.
    base = tmp_path if natural >= 114 else tmp_path / ("p" * (114 - natural - 1))
    home = relative_home("amfam", base, monkeypatch, capsys)
    app = home.build()
    cwd = whole(Path.cwd())
    assert 114 <= cwd <= 200
    # One word, so no cut ends in a space.
    long_summary = ("Declarations" * 20)[:250 - cwd - 16 - len("2026-03-15 American Family ")]
    names = []
    for month, summary in (("01", "Statement"), ("02", "Auto Policy"), ("03", long_summary)):
        doc = home.mod.Document(title="Account Statement %s" % month, category="Statement",
                                summary=summary, date="2026-%s-15" % month, account="1234")
        name = "2026-%s-15 American Family %s.pdf" % (month, summary)
        names.append(saved_as(app, doc, name, census.body_of(month)).name)
    census.saved(app)
    assert len(names[2]) <= 124
    assert [whole(app.paths.statements / n) for n in names] == [
        cwd + 12 + len(n) for n in names[:2]] + [250]
    said = home.rename()
    if not whole_path:
        assert census.NAMED_ALREADY in said, said
        return
    cut = names[2][:-len(".pdf") - 10] + ".pdf"
    assert "1 file(s) would be renamed." in said, said
    assert "%s -> %s" % (names[2], cut) in said, said
    assert whole(app.paths.statements / cut) == 240


def keeps_the_names_it_gave(tmp_path, monkeypatch, capsys) -> None:
    """A long pattern under an install deep in its file system files and
    names a document as 40491dd7 did, the three folders and the name cut to
    240 from the install, its path as long in full as it may be."""
    deep = tmp_path / ("m" * max(1, 150 - whole(tmp_path) - 1))
    home = relative_home("amfam", deep, monkeypatch, capsys)
    home.set_pattern("{account}/{kind}/{summary}/{date:yyyy-mm-dd} {summary}")
    app = home.build()
    doc = home.mod.Document(title="Account Statement", category="Statement",
                            summary=SUMMARY, date="2026-03-31", account=ACCOUNT)
    path = census.downloaded(app, doc)
    folders = Path("Statements", ACCOUNT[:60].rstrip(" ."), "Statement",
                   SUMMARY[:60].rstrip(" ."))
    room = 240 - len(str(folders)) - 1
    assert path == folders / (("2026-03-31 " + SUMMARY)[:room - 4].rstrip(" .") + ".pdf")
    assert whole(path) > 240
    census.saved(app)
    assert census.NAMED_ALREADY in home.rename()


def test_a_mac_and_the_server_keep_every_name_they_gave(tmp_path, monkeypatch, capsys):
    """N8-7. Nothing is measured whole on a Mac or PaperPull Server."""
    if sys.platform == "win32":
        pytest.skip("needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)")
    keeps_the_names_it_gave(tmp_path, monkeypatch, capsys)


def test_measured_as_a_mac_measures_every_name_is_as_it_was(tmp_path, monkeypatch, capsys,
                                                           measured):
    """N8-7, on any system, measured as a Mac and the Server measure."""
    measured(False)
    if sys.platform == "win32" and not _long_paths_work():
        pytest.skip("the path 40491dd7 gave is past 260 characters in full")
    keeps_the_names_it_gave(tmp_path, monkeypatch, capsys)


def test_an_output_folder_written_in_full_too_deep_for_a_name_says_so(
        tmp_path, monkeypatch, capsys):
    """N8-7. An output folder of 235 characters written in full is measured
    in full everywhere, as it always was. The folder of a kind in it leaves
    no room for a name, and the app's own download says so, naming
    max_path_length, before it reaches for a page. Each document of the run
    is then recorded Failed with that sentence by the app's own handler,
    which logs it once for each, as at 40491dd7."""
    out = tmp_path / ("o" * (235 - whole(tmp_path) - 1))
    assert whole(out) == 235
    home = census.Home(census.REPO / "apps" / "amfam", tmp_path, monkeypatch, capsys)
    home.config["output_dir"] = str(out)
    home.out = out
    home._write_config()
    app = home.build()
    doc = home.mod.Document(title="Account Statement", category="Statement",
                            summary="Statement", date="2026-03-31", account="1234")
    name = storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    with pytest.raises(ValueError) as e:
        census.where_its_download_saves(app, doc, name)
    assert "too deep" in str(e.value) and "max_path_length" in str(e.value)


# -- the one check for all three faults ---------------------------------------------

SUMMARIES = ["Household Goods", "Kontoauszug Übersicht Gebühren",
             "Garden Supplies and Outdoor Furniture With Delivery"]
# The names 40491dd7 gave each, under the default pattern. Each fits 240
# in full under an install as deep as a temporary folder is, so not one is
# too long for Windows.
AT_40491DD7 = {
    "amfam": ["2026-09-12 American Family Household Goods.pdf",
              "2026-10-12 American Family Kontoauszug Übersicht Gebühren.pdf",
              "2026-11-12 American Family Garden Supplies and Outdoor Furniture With "
              "Delivery.pdf"],
    "lowes": ["2026-09-12 Lowe's Household Goods Receipt.pdf",
              "2026-09-12 Lowe's Kontoauszug Übersicht Gebühren Receipt.pdf",
              "2026-09-12 Lowe's Garden Supplies and Outdoor Furniture With Delivery "
              "Receipt.pdf"],
}


@pytest.mark.parametrize("app", sorted(AT_40491DD7))
def test_an_archive_named_at_40491dd7_is_offered_nothing(app, tmp_path, monkeypatch, capsys):
    """A document app and a receipt app, in an install's own folder as
    every install runs, under the default pattern. Each name a download
    gives is the one 40491dd7 gave, and the app's own Rename, through its
    main, finds every file named already."""
    if whole(tmp_path) > 120:
        pytest.skip("the temporary folder is too deep for these names to fit in full")
    home = relative_home(app, tmp_path, monkeypatch, capsys)
    built = home.build()
    if hasattr(home.mod, "Document"):
        paths = [census.downloaded(built, home.mod.Document(
            title="Account Statement", category="Statement", summary=summary,
            date="2026-%02d-12" % (9 + i), account="1234"))
            for i, summary in enumerate(SUMMARIES)]
    else:
        paths = [census.purchased(home, built, "112-7124528-95154%02d" % i, summary=summary)
                 for i, summary in enumerate(SUMMARIES)]
    assert [p.name for p in paths] == AT_40491DD7[app]
    assert all(whole(p) <= 240 for p in paths)
    census.saved(built)
    assert census.NAMED_ALREADY in home.rename()
