"""Every file the panel, its tools and the Paperless plug-in read or write
in the shared folder goes through a helper that refuses a link there and
never waits on a pipe.

On PaperPull Server the data folder is often a share other people can
write to and leave a link or a named pipe in. A plain read followed the
link and showed, copied or wrote back what it led to, the server's password
file among the places, a plain write landed there, and a pipe held the
panel's thread for good (a private report of 2026-11-10). The helpers are
server_mode.read_plain and read_text and write_in_data, the panel's
_write_text, _replace_text and _copy_file, and the core's shared_folder.

This lists every plain file call left in those files, by its function, and
each has to be one reviewed here, with what it touches. A new one is the
gap coming back, until it is reviewed.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILES = ["gui/app.py", "gui/server_mode.py", "tools/export_purchases.py",
         "tools/export_transactions.py", "tools/add_account.py", "tools/migrate.py",
         "tools/status.py", "server/plugins/paperless/paperless.py"]
CALLS = {"read_text", "read_bytes", "write_text", "write_bytes", "copy", "copy2", "copyfile",
         "copystat", "copytree", "save", "load", "move", "open"}
HELPERS = ("server_mode.read_text", "server_mode.read_plain", "shared_folder.")

REVIEWED = {
    "gui/app.py:<module>:(HERE.parent / 'VERSION').read_text": "the app's own VERSION",
    "gui/app.py:_copy_file:shutil.copy2": "the desktop branch, the server writes with write_in_data",
    "gui/app.py:_editable_core:(info / 'direct_url.json').read_text": "the desktop .venv's own metadata",
    "gui/app.py:_hand_over:(folder / HANDED).write_text": "a private temporary folder the panel made",
    "gui/app.py:_review_list:(folder / HANDED).read_text": "a private temporary folder the panel made",
    "gui/app.py:_provider_notes:PROVIDER_CARDS.read_text": "the app's own provider cards",
    "gui/app.py:_read_settings:_settings_path().read_text": "the person's settings, never the share",
    "gui/app.py:_write_settings:tmp.write_text": "the person's settings, never the share",
    "gui/app.py:_replace_text:tmp.write_text": "the desktop branch, the server writes with write_in_data",
    "gui/app.py:_write_text:path.write_text": "the desktop branch, the server writes with write_in_data",
    "gui/app.py:ensure_core:item.read_bytes": "the app's own core, into a desktop checkout's .venv",
    "gui/app.py:ensure_core:target.read_bytes": "a desktop checkout's own .venv",
    "gui/app.py:ensure_core:shutil.copy2": "a desktop checkout's own .venv",
    "gui/app.py:favicon:icon.read_bytes": "the app's own icon",
    "gui/app.py:list_providers:(d / 'storage.py').read_text": "PaperPull's own templates",
    "gui/app.py:read:(STATIC / name).read_text": "the app's own page",
    "gui/app.py:refresh_install_code:item.read_bytes": "PaperPull's own templates",
    "gui/server_mode.py:_read:_secrets_file().read_text": "/config, never the share",
    "gui/server_mode.py:plugins:(folder / 'plugin.json').read_text": "the image's own plug-ins",
    "server/plugins/paperless/paperless.py:main:json.load": "the run's description on stdin",
    "tools/export_purchases.py:write_xlsx:wb.save": "into a file shared_folder.open_to_write opened",
    "tools/export_transactions.py:_write_xlsx:wb.save": "into a file shared_folder.open_to_write opened",
    "tools/migrate.py:_version:(Path(__file__).resolve().parents[1] / 'VERSION').read_text":
        "the app's own VERSION",
    "tools/migrate.py:export:out.write_bytes": "the archive, in a folder the caller chose",
    "tools/migrate.py:write_history:kept.write_bytes": "the desktop branch, the server passes write",
    "tools/migrate.py:write_history:tmp.write_text": "the desktop branch, the server passes write",
    "tools/status.py:write_html:out.write_text": "the command line's --html report, at a path "
                                                 "the person names, never called by the panel",
    # The safe helpers themselves, each opening with O_NOFOLLOW, and O_EXCL
    # for a new file or O_NONBLOCK for a read.
    "gui/app.py:_note_run:os.open": "a new file of its own, O_EXCL and O_NOFOLLOW",
    "gui/app.py:_open_plain:os.open": "the panel's own link-safe open",
    "gui/server_mode.py:read_plain:os.open": "the panel's link-safe reader",
    "gui/server_mode.py:write_in_data:os.open": "a new file of its own, O_EXCL and O_NOFOLLOW",
    "server/plugins/paperless/paperless.py:copy_into:os.open": "a new file, O_EXCL and O_NOFOLLOW",
    "server/plugins/paperless/paperless.py:open_plain:os.open": "the plug-in's link-safe open",
    "tools/add_account.py:_read_config:os.open": "its link-safe reader",
    "tools/add_account.py:_write_whole:os.open": "a new file of its own, O_EXCL and O_NOFOLLOW",
    "tools/status.py:_read_text:os.open": "its link-safe reader",
    # Never the share.
    "gui/server_mode.py:_write:os.open": "the password file in /config, never the share",
    "gui/app.py:_settings_path:shutil.move": "the person's settings file, never the share",
    "gui/app.py:api_aside_download:z.open": "a member of the zip it is building to hand over",
    "tools/migrate.py:_member:z.open": "a member of the history file handed in",
    # Already link-aware.
    "gui/app.py:api_remove:shutil.move": "a link at the place counts as taken on the server, "
                                         "and the folder is held inside the data folder",
}


def _found() -> set:
    found = set()
    for f in FILES:
        tree = ast.parse((REPO / f).read_text(encoding="utf-8"))
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

        def function_of(node):
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return node.name
            return "<module>"

        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = ast.unparse(n.func)
            if name.startswith(HELPERS):
                continue
            if name in ("open", "io.open"):
                pass
            elif isinstance(n.func, ast.Attribute) and n.func.attr in CALLS:
                if n.func.attr == "load" and not name.startswith("json."):
                    continue
                if n.func.attr == "save" and not name.startswith("wb."):
                    continue
            else:
                continue
            found.add("%s:%s:%s" % (f, function_of(n), name))
    return found


def test_every_plain_file_call_left_is_one_reviewed():
    unreviewed = sorted(_found() - set(REVIEWED))
    assert not unreviewed, "read or write these through the helpers, or review them: %s" % unreviewed


def test_every_reviewed_call_is_still_there():
    """So the list says what the code does, never what it once did."""
    assert not set(REVIEWED) - _found(), sorted(set(REVIEWED) - _found())
