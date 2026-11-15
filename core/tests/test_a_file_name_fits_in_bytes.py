"""A file's name fits the 255 bytes a file system holds a name in.

sanitize_component caps a name at 120 characters, which is 120 bytes in
English and less than 255 in German. ext4 and btrfs, the file systems of
PaperPull Server, and APFS on a Mac hold a name in 255 bytes of UTF-8, and
120 characters of Japanese are 360 bytes, so a long statement title in
Japanese or a name full of emoji could not be saved there at all.

So a file's name, after everything a download adds to it, the part "(2 of
3)", what tells two files apart and the " (2)" of a last resort, is cut to
255 bytes of UTF-8 on a character's boundary (storage.file_name_of and
_free_name). A part at the end of the name stays, the text before it giving
way, since Rename reads the part only from the end of a name and renames a
file that lost it as though it were the whole order. Every name of 255
bytes or less is what it was, and sanitize_component is not where the cut
is made, since it builds the keys of most apps' records.

Every name, number and title here is invented.
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

TITLE = "口座取引明細書"     # seven CJK characters, 21 bytes
EMOJI = "\U0001F389"                                     # four bytes, two UTF-16 units
NAME_MAX = 255


def size(name) -> int:
    return len(str(name).encode("utf-8"))


@pytest.fixture
def american_family(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    storage.bind(AppSpec(provider="American Family", project_dir=tmp_path, kind=DOCUMENT,
                         folders=[Folder("statements", "Statements"),
                                  *INFRASTRUCTURE_FOLDERS],
                         default_route="statements"))
    storage.set_filename_patterns({})
    folder = tmp_path / "Statements"
    folder.mkdir()
    return folder


def test_a_file_name_fits_a_posix_file_system(american_family):
    """N9-1. At 40491dd7 the name was 120 characters and 310 bytes."""
    before = "2026-03-31 American Family " + TITLE * 13 + TITLE[:2]
    name = storage.build_pdf_filename("2026-03-31", TITLE * 16, "")
    p = storage.unique_path(american_family, name, 240)
    assert size(p.name) <= NAME_MAX, size(p.name)
    assert p.name.endswith(".pdf")
    assert p.name.startswith("2026-03-31 American Family ")
    assert before.startswith(p.stem), p.stem


def written_or_failed(path: Path) -> str:
    try:
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 invented")
        return "written"
    except OSError as e:
        return "not written, %s" % e.strerror


@pytest.mark.parametrize("title", [TITLE * 9, TITLE * 16, EMOJI * 110,
                                   "Quarterly Statement " * 10])
def test_every_long_name_is_written_on_a_posix_file_system(tmp_path, title):
    """N9-2. ext4 refused each of the first three at 40491dd7."""
    if sys.platform == "win32":
        pytest.skip("needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)")
    if str(tmp_path.resolve()).startswith("/mnt/"):
        pytest.skip("the temporary folder is on a Windows drive, set TMPDIR=/tmp")
    name = storage.build_pdf_filename("2026-03-31", title, "")
    p = storage.unique_path(tmp_path, name, 240)
    assert written_or_failed(p) == "written", p.name
    assert os.listdir(tmp_path) == [p.name]


def test_a_name_of_emoji_is_cut_between_two_characters(tmp_path):
    """N9-3. Never half of a character, and never the mark a decoder puts
    for one."""
    name = storage.build_pdf_filename("2026-03-31", EMOJI * 110, "")
    p = storage.unique_path(tmp_path, name, 240)
    assert size(p.name) <= NAME_MAX
    assert "�" not in p.name
    assert p.name.encode("utf-8").decode("utf-8") == p.name
    assert p.stem.endswith(EMOJI), ascii(p.stem[-3:])
    assert p.stem.startswith("2026-03-31 Testco " + EMOJI)


def test_five_files_of_one_long_name_are_five_names(tmp_path):
    """N9-4. The " (2)" of a last resort and what tells two files apart are
    inside the 255 bytes, and no two cut names are one."""
    name = storage.build_pdf_filename("2026-03-31", TITLE * 16, "")
    names = []
    for _ in range(5):
        p = storage.unique_path(tmp_path, name, 240)
        p.write_bytes(b"%PDF-1.4")
        names.append(p.name)
    for _ in range(5):
        p = storage.unique_path(tmp_path, name, 240, distinguisher="112-7124528-9515453")
        p.write_bytes(b"%PDF-1.4")
        names.append(p.name)
    assert len({n.lower() for n in names}) == 10, names
    for n in names:
        assert size(n) <= NAME_MAX and n.endswith(".pdf") and "�" not in n, n
    assert sorted(os.listdir(tmp_path)) == sorted(names)


def test_a_part_at_the_end_of_a_name_stays_when_it_is_cut(tmp_path):
    """N9-5. 18 + 240 + 17 bytes and the ending, so the cut has to reach
    it. The 120-character cap kept the part at 40491dd7."""
    name = storage.build_pdf_filename("2026-03-31", TITLE * 11 + TITLE[:3], "Invoice",
                                      part=(2, 3))
    assert len(name) - 4 <= 120 and size(name) <= NAME_MAX
    assert name.endswith(" (2 of 3).pdf"), name
    assert name.startswith("2026-03-31 Testco " + TITLE)
    p = storage.unique_path(tmp_path, name, 240, distinguisher="112-7124528-9515453")
    assert p.name == name
    p.write_bytes(b"%PDF-1.4")
    # The second of one name, told apart by its order number, which stays
    # whole after the part, as Rename reads them (renaming._part_of), the
    # summary giving way for both.
    again = storage.unique_path(tmp_path, name, 240, distinguisher="112-7124528-9515453")
    assert again.name.endswith(" (2 of 3) 112-7124528-9515453.pdf"), again.name
    assert size(again.name) <= NAME_MAX
    again.write_bytes(b"%PDF-1.4")
    third = storage.unique_path(tmp_path, name, 240, distinguisher="112-7124528-9515453")
    assert third.name.endswith(" (2 of 3) 112-7124528-9515453 (2).pdf"), third.name
    assert size(third.name) <= NAME_MAX


def test_a_companion_named_from_a_long_first_file_keeps_its_part(tmp_path):
    """N9-5. Wealthfront names a form set's other files from the first's
    stem, "<stem> (2 of 3)", and hands that to unique_path."""
    first = storage.build_pdf_filename("2026-03-31", TITLE * 16, "")
    assert size(first) <= NAME_MAX
    stem = "%s (2 of 3)" % Path(first).stem
    for ending in (".xls", ".pdf"):
        p = storage.unique_path(tmp_path, stem + ending, 240)
        assert p.name.endswith(" (2 of 3)" + ending), p.name
        assert size(p.name) <= NAME_MAX
        assert first.startswith(p.name[:-len(" (2 of 3)" + ending)])


def test_sanitize_component_still_cuts_at_120_characters():
    """N9-6. It builds record keys, so it cuts where it always did."""
    assert storage.sanitize_component(TITLE * 30) == (TITLE * 18)[:120]


# The keys each app gives a document of that title for account "...1234",
# as 40491dd7 builds them.
LONG_KEYS = {
    "amfam": "Statement:2026-01-15:" + TITLE * 8 + TITLE[:4] + ":...1234",
    "amazonvisa": "Statement:2026-01-15:...1234:" + TITLE * 17 + TITLE[:1],
    "direkt1822": "Statement:2026-01-15:...1234:" + TITLE * 17 + TITLE[:1],
    "dkb": "Statement:2026-01-15:...1234:" + TITLE * 17 + TITLE[:1],
}


@pytest.mark.parametrize("app", sorted(LONG_KEYS))
def test_a_key_built_from_a_long_title_is_as_it_was(app, monkeypatch):
    """N9-6."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    mod = census.load(census.REPO / "apps" / app)
    doc = mod.Document(title=TITLE * 30, category="Statement", summary="Statement",
                       date="2026-01-15", account="...1234")
    assert doc.key == LONG_KEYS[app]


# Names the German apps and an English one give, as 40491dd7 gave them.
UNCHANGED = [
    ("Kontoauszug Girokonto Übersicht",
     "2026-03-31 Testco Kontoauszug Girokonto Übersicht.pdf"),
    ("Kontoauszug Girokonto Übersicht der Umsätze und Gebühren für das "
     "Quartal mit Zinsabschluss und Änderungsmitteilung zum Vertrag",
     "2026-03-31 Testco Kontoauszug Girokonto Übersicht Der Umsätze Und "
     "Gebühren Für Das Quartal Mit Zinsabschluss Und Änderun.pdf"),
    ("Jahressteuerbescheinigung 2025 für Gemeinschaftskonto Straße",
     "2026-03-31 Testco Jahressteuerbescheinigung 2025 Für Gemeinschaftskonto "
     "Straße.pdf"),
    ("Quarterly Statement " * 10,
     "2026-03-31 Testco " + ("Quarterly Statement " * 6)[:102] + ".pdf"),
]


@pytest.mark.parametrize("summary,expected", UNCHANGED)
def test_a_name_of_255_bytes_or_less_is_as_it_was(tmp_path, summary, expected):
    """N9-7."""
    name = storage.build_pdf_filename("2026-03-31", summary, "")
    assert name == expected
    assert storage.unique_path(tmp_path, name, 240).name == expected


# -- Rename over a name 40491dd7 saved past 255 bytes -------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    return census.Home(census.REPO / "apps" / "amfam", tmp_path, monkeypatch, capsys)


def test_rename_offers_to_cut_a_name_saved_past_255_bytes_and_nothing_else(home):
    """N9-8. NTFS holds a name of 255 UTF-16 units, so a Windows install
    saved this one at 40491dd7. Rename offers to cut it, which is expected,
    and the archive's other names stay."""
    if sys.platform != "win32":
        pytest.skip("only NTFS holds a name of more than 255 bytes")
    app = home.build()
    doc = home.mod.Document(title="Account Statement", category="Statement",
                            summary=TITLE * 16, date="2026-01-15", account="1234")
    listed = doc.to_dict()
    listed["state"] = State.DISCOVERED.value
    app.discovery.update(doc.key, listed, save=False)
    old_name = "2026-01-15 American Family " + TITLE * 13 + TITLE[:2] + ".pdf"
    assert size(old_name) > NAME_MAX
    old = app.paths.statements / old_name
    old.write_bytes(census.body_of("1234"))
    doc.pdf_path, doc.pdf_filename = str(old), old.name
    doc.downloaded_ok = True
    app._record(doc, State.COMPLETED)
    app._write_row(doc, "Downloaded", State.COMPLETED.value)
    other = home.mod.Document(title="Account Statement", category="Statement",
                              summary="Monthly Statement", date="2026-02-15", account="5678")
    census.downloaded(app, other, census.body_of("5678"))
    census.saved(app)
    said = home.rename()
    assert "1 file(s) would be renamed." in said, said
    new_name = str(storage.build_pdf_filename("2026-01-15", TITLE * 16, "", record=doc))
    assert size(new_name) <= NAME_MAX
    assert "%s -> %s" % (old_name, new_name) in said, said
