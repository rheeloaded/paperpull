"""No app moves or deletes a file because a record names it, unless the
file is one the account holds.

A record names its file, and a history imported from another computer, or
a progress.json edited by hand, can name any file on this one. AT&T's
repair at start, American Family's same-PDF check and NetBenefits' held
statements each moved the file a record named, so such a history moved a
file of this computer's into Manual Review (a private report of
2026-11-10). Each asks renaming.held_document first now, which holds only a
document in a folder the account files in once links and ".." are
followed, and is never a link.

This reads every function of every app that reads a record's path or the
account's records, and moves, renames or deletes a file, and asks for that
check in it. A function that moves only the file its own run just wrote is
listed here with that reason. On 2b761d6c it flagged the three above.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Never into a virtual environment a checkout keeps beside an app's code,
# nor a copy a build or an install made (test_no_census_reads_a_copy_a_build_made).
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
        "site-packages"}
RECORD_KEYS = {"pdf_path", "file"}
# Path.replace and Path.rename take one argument, where str.replace takes two.
MOVES = {"replace": 1, "rename": 1, "unlink": None}
CALLS = {"os.replace", "os.rename", "os.renames", "os.remove", "os.unlink", "shutil.move",
         "shutil.rmtree"}
CHECKS = {"held_document", "held_row"}

# Functions that move only what their own run just wrote. Reviewed 2026-11-14.
JUST_WRITTEN = {
    "amfam/amfam_docs.py:download_one": "the download it just wrote, or its quarantine",
    "anthem/anthem_docs.py:_save_collected": "the PDF and companions it just wrote",
    "bilt/bilt_docs.py:download_one": "the download it just wrote, or its quarantine",
    "netbenefits/netbenefits_docs.py:_own_or_combined": "out_path, a download or a held file "
                                                       "_judge_held checked with held_document",
    "robinhood/robinhood_docs.py:_settle_tax_form": "the tax form download_one just wrote",
    "spectrum/spectrum_docs.py:download_one": "the download it just wrote, or its quarantine",
}


def _sources():
    for top, dirs, files in os.walk(REPO / "apps"):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(top) / name


def _reads_records(fn) -> bool:
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value in RECORD_KEYS):
            return True
        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and n.slice.value in RECORD_KEYS):
            return True
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and (
                n.attr == "pdf_path" or (n.attr == "progress" and ast.unparse(n.value) == "self")):
            return True
    return False


def _moves(fn) -> list:
    out = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        if ast.unparse(n.func) in CALLS:
            out.append(n.lineno)
        elif isinstance(n.func, ast.Attribute) and n.func.attr in MOVES:
            want = MOVES[n.func.attr]
            if want is None or (len(n.args) == want and not n.keywords):
                out.append(n.lineno)
    return out


def _checks(fn) -> bool:
    return any(isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] in CHECKS
               for n in ast.walk(fn))


def _flagged() -> dict:
    found = {}
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        where = path.relative_to(REPO / "apps").as_posix()
        for fn in ast.walk(tree):
            if (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _reads_records(fn)
                    and _moves(fn) and not _checks(fn)):
                found["%s:%s" % (where, fn.name)] = _moves(fn)
    return found


def test_a_file_a_record_names_is_moved_only_once_the_account_is_found_to_hold_it():
    found = _flagged()
    unchecked = {k: v for k, v in found.items() if k not in JUST_WRITTEN}
    assert not unchecked, ("these move or delete a file and read the records, with no "
                           "renaming.held_document in them: %s" % unchecked)


def test_every_function_listed_as_moving_what_it_just_wrote_is_still_there():
    """So the list is the review it says it is, never a list of names gone."""
    gone = set(JUST_WRITTEN) - set(_flagged())
    assert not gone, gone
