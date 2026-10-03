"""Writes down where each failing test failed, for tools/run_all_tests.py.

The runner keeps a suite's whole pytest output where it can be read in
full and prints a short account of each failure. That account needs the
frames of every failing test, file, line and function, and pytest's text
does not carry them in one form. The location line of a long entry names
no function, and which section belongs to which test has to be guessed
from the order. So this takes them from the exception itself, the way
pytest holds it, and writes one JSON line per failure to the file named
by PAPERPULL_WHERE_IT_FAILED.

It records facts and decides nothing. Which of them may be printed, and
in what form, is the runner's choice, made in one place.

It must never change a run. With no file named it does nothing, and any
error of its own is swallowed rather than allowed to become the test's.
"""
from __future__ import annotations

import json
import os
import site
import sys
import sysconfig

ENV = "PAPERPULL_WHERE_IT_FAILED"

# Bounds, so one runaway failure cannot fill the disk or the summary. A
# recursion error has a thousand frames, and the ends are what matter.
FIRST_FRAMES = 20
LAST_FRAMES = 60
MESSAGE_CHARS = 4000
CHAIN = 5
GROUP_MEMBERS = 3


def _own_dirs() -> tuple:
    """pytest's and pluggy's own folders. Their frames are the machinery
    that called the test, which pytest leaves out of what it shows too."""
    out = []
    for name in ("_pytest", "pluggy", "pytest"):
        f = getattr(sys.modules.get(name), "__file__", None)
        if f:
            out.append(os.path.normcase(os.path.dirname(os.path.abspath(f))) + os.sep)
    return tuple(out)


def _libraries() -> list:
    """Where this interpreter keeps the standard library and installed
    packages, so the runner can tell a library frame from anything else
    without knowing which interpreter ran the suite."""
    paths = set()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            paths.add(p)
    try:
        paths.update(p for p in site.getsitepackages() if p.rstrip("\\/").endswith("site-packages"))
        paths.add(site.getusersitepackages())
    except Exception:
        pass
    return sorted(os.path.abspath(p) for p in paths if p)


def _hidden(frame, filename: str, own: tuple) -> bool:
    if filename.startswith("<frozen importlib"):
        return True
    if os.path.normcase(os.path.abspath(filename)).startswith(own):
        return True
    try:
        flag = frame.f_locals.get("__tracebackhide__", frame.f_globals.get("__tracebackhide__"))
    except Exception:
        return False
    return bool(flag) and not callable(flag)


def _frames(tb, own: tuple) -> dict:
    kept = []
    while tb is not None:
        frame = tb.tb_frame
        name = frame.f_code.co_filename
        if not _hidden(frame, name, own):
            path = name if name.startswith("<") else os.path.abspath(name)
            kept.append([path, tb.tb_lineno, frame.f_code.co_name])
        tb = tb.tb_next
    left_out = max(0, len(kept) - FIRST_FRAMES - LAST_FRAMES)
    if left_out:
        kept = kept[:FIRST_FRAMES] + kept[-LAST_FRAMES:]
    return {"frames": kept, "left_out": left_out, "after": FIRST_FRAMES if left_out else None}


def _type_name(exc) -> str:
    t = type(exc)
    mod = getattr(t, "__module__", "") or ""
    qual = getattr(t, "__qualname__", t.__name__)
    return qual if mod == "builtins" else mod + "." + qual


def _message(exc) -> str:
    try:
        return str(exc)[:MESSAGE_CHARS]
    except Exception:
        return ""


def _chain(exc, own: tuple) -> list:
    """The exception and what led to it, the first cause first, the way
    Python prints a chained traceback."""
    seen, chain = set(), []
    while exc is not None and id(exc) not in seen and len(chain) < CHAIN:
        seen.add(id(exc))
        entry = {"type": _type_name(exc), "message": _message(exc)}
        entry.update(_frames(exc.__traceback__, own))
        chain.append(entry)
        if exc.__cause__ is not None:
            exc = exc.__cause__
        elif exc.__context__ is not None and not exc.__suppress_context__:
            exc = exc.__context__
        else:
            exc = None
    return chain[::-1]


def _errors(exc, own: tuple) -> list:
    """One chain, or one per member of an exception group as well. pytest
    raises a group when more than one finalizer fails in a teardown."""
    out = [_chain(exc, own)]
    for member in list(getattr(exc, "exceptions", None) or [])[:GROUP_MEMBERS]:
        if isinstance(member, BaseException):
            out.append(_chain(member, own))
    return out


def _as_summarized(node, nodeid: str) -> str:
    try:
        return node.config.cwd_relative_nodeid(nodeid)
    except Exception:
        return nodeid


def pytest_exception_interact(node, call, report):
    """Called by pytest for a failure that raised, in collection, setup,
    the test itself or teardown. Not for a skip or an expected failure."""
    path = os.environ.get(ENV)
    if not path:
        return
    try:
        exc = call.excinfo.value if call.excinfo is not None else None
        if exc is None:
            return
        record = {
            "nodeid": report.nodeid,
            # The same test as pytest's summary line names it, relative to
            # the folder the suite ran in, which is not the checkout's root.
            "as_summarized": _as_summarized(node, report.nodeid),
            "when": getattr(report, "when", None) or "collect",
            "errors": _errors(exc, _own_dirs()),
            "libraries": _libraries(),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
