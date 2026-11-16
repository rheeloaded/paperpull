"""Every app names a file that every system it runs on holds and shows.

Three faults of one kind, found on 2026-11-14 and fixed in the core. A name
a pattern started with American Family's masked account, "...1234", was a
hidden file on a Mac, on Linux and on PaperPull Server's share. The path
limit was measured from the install while Windows counts the whole path.
And a name was counted in characters while ext4, btrfs and APFS hold 255
bytes of UTF-8, so a long title in Japanese could not be saved there.

So every app is bound to its own AppSpec, as its storage module binds it,
in an install's folder deep in its file system, with output_dir "." as
every install has it. Page text that starts with dots, long Japanese and
long emoji go in every field, under the default pattern and three of a
person's (a name alone, folders and a name, folders and a part), and each
name is filed with unique_path in every folder the app routes a document
to, and in Manual Review, and written. Each saved name has to start with
neither a dot nor a space, fit 255 bytes of UTF-8, decode cleanly, keep
to max_path_length measured as the system measures it, and lie in its
folder, and the File names page (naming.preview) has to show the very name
a run builds.

And the keys. sanitize_component builds the keys of most apps' records,
and neither fix may change one, or every such document would look new and
be fetched again beside its copy. So each app's key for a document titled
and accounted with those values is built twice, with the core as it is and
with a copy of sanitize_component as it was at 40491dd7, and the two have
to be one.

Every name, number and account here is invented.
"""
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import naming, storage as core_storage  # noqa: E402
from paperpull_core.characters import whole_characters  # noqa: E402
from paperpull_core.spec import RECEIPT  # noqa: E402

import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# What a build or an install leaves beside the source, never an app.
NOT_APPS = {".venv", "venv", "build", "dist", "site-packages", "node_modules", "tests",
            "__pycache__"}

DATE = "2026-01-15"
TITLE = "口座取引明細書"
EMOJI = "\U0001F389"
# A masked account, dots and spaces, long Japanese, and long emoji after dots.
VALUES = ["...1234", ". .hidden", TITLE * 30, "..." + EMOJI * 110]
PATTERNS = [None, "{account} {date:yyyy-mm-dd} {summary}",
            "{account}/{store}/{type}/{date:yyyy-mm-dd} {summary}",
            "{provider}/{account}/{date:yyyy-mm-dd} {summary}[ ({part})]"]
LIMIT = 240
NAME_MAX = 255


def apps():
    """Every app, found by a storage module of its own that binds the core
    to its AppSpec, never by a list of names."""
    found = []
    for folder in sorted((REPO / "apps").iterdir()):
        own = folder / "storage.py"
        if (folder.is_dir() and folder.name not in NOT_APPS and not folder.name.startswith(".")
                and own.is_file() and "bind(SPEC)" in own.read_text(encoding="utf-8-sig")):
            found.append(folder)
    return found


APPS = apps()


def test_there_are_apps_to_check():
    assert len(APPS) >= 90, [a.name for a in APPS]
    assert {"amfam", "amazon", "target", "wealthfront"} <= {a.name for a in APPS}


def whole(path) -> int:
    """How long Windows counts a path, from the drive, in UTF-16 units."""
    return len(os.path.abspath(str(path)).encode("utf-16-le")) // 2


def measured(path) -> int:
    """How long max_path_length counts a path on this system. The whole
    path on Windows, where its 260-character limit is, and the path as
    written on a Mac and on PaperPull Server, as it always was."""
    return whole(path) if sys.platform == "win32" else len(str(path))


def bound_to(app: Path, monkeypatch):
    """The app's own storage module, loaded under a name of its own, which
    binds the core to its AppSpec. Put back after."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    found = importlib.util.spec_from_file_location("_storage_of_%s" % app.name,
                                                   app / "storage.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    core_storage.set_filename_patterns({})
    return module


def routed(paths, spec) -> list:
    """Every folder the app routes a document to, and Manual Review."""
    folders = {paths.folder_for(key) for key in spec.routes}
    if spec.default_route:
        folders.add(paths.folder_for(""))
    paths.manual_review.mkdir(parents=True, exist_ok=True)
    folders.add(paths.manual_review)
    return sorted(folders, key=str)


def inside(path: Path, folder: Path) -> bool:
    """Whether a path lies in a folder. Nothing here is a link, so the path
    as written says where it is."""
    there, home = os.path.abspath(path), os.path.abspath(folder)
    return os.path.commonpath([there, home]) == home


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_every_name_an_app_saves_is_held_and_shown_everywhere(app, tmp_path, monkeypatch):
    mod = bound_to(app, monkeypatch)
    spec = core_storage.spec()
    assert spec.provider and Path(spec.project_dir) == app
    # An install deep in its file system, started in its own folder.
    install = tmp_path / ("i" * max(1, 150 - whole(tmp_path) - 1))
    install.mkdir()
    monkeypatch.chdir(install)
    paths = mod.Paths(".", spec, documents_dir="")
    receipts = spec.kind == RECEIPT
    kind = "Receipt" if receipts else ""
    wrong = []
    for pattern in PATTERNS:
        for value in VALUES:
            record = {"account": value, "store_info": value, "purchase_type": value,
                      "order_number": value, "document_id": value, "category": value,
                      "summary": value, "date": DATE}
            part = (2, 3) if pattern and "{part}" in pattern else None
            name = mod.build_pdf_filename(DATE, value, kind, part=part, record=record,
                                          pattern=pattern)
            if pattern and not part:
                shown = naming.preview(pattern, record, provider=spec.provider,
                                       receipts=receipts, document_type=kind)
                built = "%s/%s" % (name.folder, name) if name.folder else str(name)
                if shown != built:
                    wrong.append("the page shows %r, a run builds %r" % (shown, built))
            for folder in routed(paths, spec):
                p = mod.unique_path(folder, name, LIMIT, distinguisher=value)
                said = "%s under %r in %s, %r" % (ascii(value[:12]), pattern, folder.name,
                                                  ascii(p.name[:40]))
                try:
                    p.write_bytes(b"%PDF-1.4 invented")
                except OSError as e:
                    wrong.append("not written (%s), %s" % (e.strerror, said))
                if p.name[:1] in (".", " "):
                    wrong.append("hidden, " + said)
                if len(p.name.encode("utf-8")) > NAME_MAX:
                    wrong.append("%d bytes, %s" % (len(p.name.encode("utf-8")), said))
                if "�" in p.name or whole_characters(p.name) != p.name:
                    wrong.append("half a character, " + said)
                if measured(p) > LIMIT:
                    wrong.append("a path of %d, %s" % (measured(p), said))
                if not inside(p, folder):
                    wrong.append("outside its folder, " + said)
    assert not wrong, "%s\n%s" % (app.name, "\n".join(wrong[:20]))


# -- the keys ----------------------------------------------------------------------

# sanitize_component as it was at 40491dd7, the day both fixes were made.
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_component_as_it_was(name: str, max_len: int = 120) -> str:
    name = _INVALID_CHARS.sub("", whole_characters(name or ""))
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(" .")
    if not name:
        name = "Unnamed"
    stem = name.split(".")[0].strip().upper()
    if stem in _RESERVED:
        name = f"{name} File"
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
        if not name:
            name = "Unnamed"
    return name


KEY_VALUES = ["...1234", ". .hidden", "..", TITLE * 29, EMOJI * 110, "CON", "...CON",
              "a\ud800b", "x" * 300, " Joint/Savings. ", "Kontoauszug Übersicht"]


@pytest.mark.parametrize("max_len", [120, 60, 40])
def test_sanitize_component_is_what_it_was(max_len):
    for value in KEY_VALUES:
        assert core_storage.sanitize_component(value, max_len) == \
            sanitize_component_as_it_was(value, max_len), ascii(value[:20])


KEYED = [a for a in census.APPS if (a / "storage.py").is_file()]


def record_of(mod, value: str):
    """A record of this app's own class, titled and accounted with
    `value`, or None for an app whose record takes neither."""
    Document = getattr(mod, "Document", None)
    if Document is not None:
        try:
            return Document(title=value, category="Statement", summary=value, date=DATE,
                            account=value)
        except TypeError:
            pass
    Purchase = getattr(mod, "Purchase", None)
    if Purchase is not None:
        try:
            return Purchase(purchase_type="Online", purchase_date=DATE, order_number=value,
                            total="$1.00", summary=value, document_type="Receipt",
                            confidence="High")
        except TypeError:
            pass
    return None


@pytest.mark.parametrize("app", KEYED, ids=[a.name for a in KEYED])
def test_every_key_is_what_it_was(app, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    mod = census.load(app)
    records = [record_of(mod, v) for v in ("...1234", TITLE * 29, EMOJI * 110)]
    if records[0] is None:
        pytest.skip("%s keeps no record of a class this builds" % app.name)
    now = [r.key for r in records]
    live = core_storage.sanitize_component
    with pytest.MonkeyPatch.context() as patch:
        for module in list(sys.modules.values()):
            if getattr(module, "sanitize_component", None) is live:
                patch.setattr(module, "sanitize_component", sanitize_component_as_it_was)
        before = [r.key for r in records]
    assert now == before
