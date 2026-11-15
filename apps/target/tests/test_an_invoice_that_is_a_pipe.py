"""An invoice an index row or an order's list names that is a named pipe
holds nothing.

Target reads a saved invoice to know which of the order's invoices it is,
for every row of the order in the receipt index (_indexed_invoices), for
an entry of the order's list another order claims (_lost), and for another
order's claim on a file (_another). A row or an entry naming a named pipe,
which someone on PaperPull Server's share can leave at a name, held each of
these for good, since pdf_reader opened and read the path in the run's own
process before any time limit (the bug hunt of 2026-11-14, finding 4). The
pipe is answered at once now as a file that is no invoice.

A named pipe is POSIX, skipped on Windows with the reason and run under
WSL, and a Windows named pipe that never writes stands in for it here,
since its read waits as the other's open does. Every number is invented.
"""
import importlib.util
import os
import sys
import threading
import traceback
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import storage  # noqa: E402,F401  binds this provider's AppSpec
from paperpull_core.models import ONLINE, Purchase  # noqa: E402

POSIX_ONLY = "needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)"


def _harness():
    """test_every_invoice_of_an_order.py, for an_app, index_rows and its
    made-up order."""
    spec = importlib.util.spec_from_file_location(
        "target_pipe_harness", HERE / "test_every_invoice_of_an_order.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = _harness()


def within(seconds, fn, *args, **kwargs):
    """fn(*args, **kwargs) in a thread, failing if it is still waiting after
    `seconds`, with where it waits."""
    got = {}

    def run():
        try:
            got["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            got["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        frame = sys._current_frames().get(t.ident)
        lines = [f for f in traceback.extract_stack(frame)
                 if "paperpull_core" in f.filename or "apps" in Path(f.filename).parts]
        where = ", ".join("%s:%d %s" % (Path(f.filename).name, f.lineno, f.name)
                          for f in lines[-6:])
        raise AssertionError("still waiting after %s s, in %s" % (seconds, where))
    return got


@pytest.fixture
def app(tmp_path):
    return harness.an_app(tmp_path)


@pytest.fixture(params=["named pipe", "Windows named pipe"])
def pipe(request, app):
    """A pipe where an invoice was, which no one ever writes to."""
    if request.param == "named pipe":
        if not hasattr(os, "mkfifo"):
            pytest.skip(POSIX_ONLY)
        at = app.paths.invoices / "Games (2 of 2).pdf"
        at.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(at)
        yield at
        try:
            os.close(os.open(at, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        return
    if os.name != "nt":
        pytest.skip("a Windows named pipe, which only Windows makes")
    import _winapi
    name = r"\\.\pipe\paperpull-test-%d-%s" % (os.getpid(), os.urandom(4).hex())
    handles = [_winapi.CreateNamedPipe(name, _winapi.PIPE_ACCESS_DUPLEX, 0,
                                       _winapi.PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0,
                                       _winapi.NULL) for _ in range(64)]
    yield Path(name)
    for h in handles:
        _winapi.CloseHandle(h)


def test_an_index_row_naming_a_pipe_is_no_invoice_on_file(app, pipe):
    """An order saved before every invoice was walked is known by its index
    rows, and each row's file is read for which invoice it is."""
    purchase = harness.tipped_purchase()
    harness.index_rows(app, purchase.order_number, pipe)
    assert within(5, app._invoices_on_file, purchase) == {"value": []}


def test_an_entry_naming_a_pipe_another_order_claims_is_lost(app, pipe):
    purchase = harness.tipped_purchase()
    entry = {"file": str(pipe), "part": "2 of 2", "number": "10000000000000041", "kept": True}
    got = within(5, app._lost, entry, purchase, lambda file, number: True)
    assert got == {"value": True}, got


def test_another_orders_claim_on_a_pipe_is_answered_at_once(app, pipe):
    other = Purchase(purchase_type=ONLINE, purchase_date=harness.TIPPED.iso,
                     order_number=harness.OTHER)
    app.progress.update(other.key, dict(other.to_dict(), invoices=[
        {"file": str(pipe), "part": "1 of 1", "number": "", "kept": True}]))
    another = app._another(app.index_csv.read_all(), app.progress.data)
    got = within(5, another, str(pipe), harness.TIPPED.number)
    assert isinstance(got.get("value"), bool), got
