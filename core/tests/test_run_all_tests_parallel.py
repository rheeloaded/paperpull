"""tools/run_all_tests.py runs suites side by side, one run at a time.

By October 2026 the whole suite took an hour and a half on the machine it
is run on before every push, one suite after another, while that machine
had processors to spare and two sessions' runs often slowed each other.
These check what replaced that. Suites really overlap in time, a run that
runs out of time ends with everything it started, the parts CI splits the
suites into cover each suite once, a second run waits for the first one's
lock, a run of the same checkout is named rather than waited for, and
--stop ends a run with the processes it started.
"""
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

rat = pytest.importorskip("run_all_tests")


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out.split()
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def gone(pid: int, within: float = 15.0) -> bool:
    end = time.time() + within
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.5)
    return False


def suite_with(root: Path, name: str, test: str) -> Path:
    d = root / name
    (d / "tests").mkdir(parents=True)
    (d / "tests" / "test_it.py").write_text(textwrap.dedent(test).lstrip("\n"), encoding="utf-8")
    return d


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """main() over suites of our making, with output, times and the lock
    kept in tmp_path, never in the checkout or the machine's real lock."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(rat, "OUTPUT", tmp_path / "test-output")
    monkeypatch.setattr(rat, "TIMES", tmp_path / "times.json")
    monkeypatch.setattr(rat, "LOCK_DIR", tmp_path / "lock")
    monkeypatch.setattr(rat, "candidates", lambda: [])
    monkeypatch.setattr(rat, "python_for", lambda d, kind, spares: (Path(sys.executable), []))

    def make(dirs: dict, times: dict = None):
        monkeypatch.setattr(rat, "suites", lambda quick: [(n, d, "app") for n, d in dirs.items()])
        (tmp_path / "times.json").write_text(json.dumps(times or {}), encoding="utf-8")
    return make


# Each suite's one test says it has started, then waits for the other two to
# say so before it ends. All three pass only when all three were running at
# once, however long each one's pytest took to start. They used to sleep four
# seconds and compare times instead, and on 2026-10-03 that failed under load,
# when one suite's pytest started more than four seconds after another's. Each
# says so in a file of its own, since lines that several processes append to
# one file can overwrite each other on Windows, which failed the old way too.
MEET = """
    import os, time
    def test_meet():
        folder, me = os.environ["STARTED_IN"], os.path.basename(os.getcwd())
        open(os.path.join(folder, me), "w").close()
        limit = float(os.environ["WAIT_SECONDS"])
        end = time.monotonic() + limit
        while True:
            missing = [n for n in os.environ["WAIT_FOR"].split()
                       if not os.path.exists(os.path.join(folder, n))]
            if not missing or time.monotonic() > end:
                break
            time.sleep(0.05)
        assert not missing, "%s waited %gs for %s, which never started" % (me, limit, " and ".join(missing))
    """


def suites_that_meet(fake_run, tmp_path, monkeypatch, seconds):
    names = ("alpha", "beta", "gamma")
    (tmp_path / "started").mkdir()
    monkeypatch.setenv("STARTED_IN", str(tmp_path / "started"))
    monkeypatch.setenv("WAIT_FOR", " ".join(names))
    monkeypatch.setenv("WAIT_SECONDS", str(seconds))
    fake_run({n: suite_with(tmp_path / "s", n, MEET) for n in names})


def test_suites_run_side_by_side_and_each_is_reported_once(fake_run, tmp_path, monkeypatch, capsys):
    suites_that_meet(fake_run, tmp_path, monkeypatch, seconds=60)
    code = rat.main(["--jobs", "3"])
    out = capsys.readouterr().out
    assert code == 0, "the three suites were never all running at once\n" + out
    for n in ("alpha", "beta", "gamma"):
        said = [ln for ln in out.splitlines() if ln.split()[:2] == ["ok", n]]
        assert len(said) == 1 and "1 passed" in said[0], out
    assert "3 suites, 3 at a time, longest first" in out


def test_one_at_a_time_the_same_suites_fail(fake_run, tmp_path, monkeypatch, capsys):
    # What keeps the test above honest. One at a time, the first suite waits
    # for two that cannot start until it ends, and the second for the third.
    suites_that_meet(fake_run, tmp_path, monkeypatch, seconds=1)
    assert rat.main(["--jobs", "1"]) == 1
    out = capsys.readouterr().out
    assert "alpha waited 1s for beta and gamma, which never started" in out, out
    assert "beta waited 1s for gamma, which never started" in out, out
    assert sum(1 for ln in out.splitlines() if ln.split()[:2] == ["ok", "gamma"]) == 1, out


def test_one_at_a_time_keeps_the_old_order(fake_run, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(rat, "run_suite", lambda d, py, timeout=1800: (seen.append(d.name) or ("1 passed", 0, [])))
    fake_run({n: tmp_path / n for n in ("core", "gui", "amazon")}, {"amazon": 500, "core": 5})
    assert rat.main(["--jobs", "1"]) == 0
    assert seen == ["core", "gui", "amazon"]


def test_side_by_side_the_longest_start_first():
    # A suite with no time yet counts as the middle one, 517 here, and a tie
    # goes by name, so the order never depends on the order handed in.
    times = {"target": 649, "statefarm": 517, "core": 425, "gui": 5}
    assert rat.longest_first(["gui", "core", "unknown", "target", "statefarm"], times) == \
        ["target", "statefarm", "unknown", "core", "gui"]


def test_the_parts_cover_every_suite_once_and_finish_close_together():
    times = rat.load_times(REPO / "tools" / "suite_times.json")
    names = sorted(times) + ["a_new_app"]
    parts = [rat.shard_of(names, times, k, 4) for k in range(1, 5)]
    assert sorted(n for p in parts for n in p) == sorted(names)
    assert parts == [rat.shard_of(names, times, k, 4) for k in range(1, 5)], "not the same parts twice"
    loads = [sum(rat.expected(n, times) for n in p) for p in parts]
    assert max(loads) <= sum(loads) / 4 + max(times.values())


def test_a_part_runs_only_its_own_suites(fake_run, tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(rat, "run_suite", lambda d, py, timeout=1800: (seen.append(d.name) or ("1 passed", 0, [])))
    times = {"a": 100, "b": 90, "c": 20, "d": 10}
    fake_run({n: tmp_path / n for n in times}, times)
    assert rat.main(["--shard", "1/2", "--jobs", "1"]) == 0
    assert sorted(seen) == sorted(rat.shard_of(list(times), times, 1, 2)) == ["a", "d"]
    assert "part 1 of 2, 2 suites" in capsys.readouterr().out


def test_a_bad_part_is_refused():
    for bad in ("0/4", "5/4", "two", "1/0"):
        with pytest.raises(SystemExit):
            rat.parse_shard(bad)


# The suite's one test starts a process of its own, as a test that opens a
# browser does, says which processes are its pytest and that one, then sleeps
# for ten minutes, longer than anything here waits for it, so only the runner
# can end them. The numbers are written under another name and moved into
# place, so they are there whole or not at all, wherever the runner stops the
# suite.
SLEEPY = """
    import os, subprocess, sys, time
    def test_forever():
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        with open(%(part)r, "w") as f:
            f.write(" ".join(map(str, (os.getpid(), child.pid))))
        os.replace(%(part)r, %(pid)r)
        time.sleep(600)
    """

# How long a runner gets, once a suite is out of time, to end it and come back.
ENDS_WITHIN = 60


def end_tree(pid: int) -> None:
    """End a process and what it started, when the runner left them running.
    Not with rat.stop_tree, which is what is being checked."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def started(pid_file: Path) -> tuple:
    """The suite's pytest and the process its test started, once it has."""
    return tuple(int(p) for p in pid_file.read_text().split()) if pid_file.exists() else ()


def run_watched(d: Path, limit: int, pid_file: Path):
    """rat.run_suite, failing the test when it has not come back ENDS_WITHIN
    seconds after the suite's limit, and ending what it left. Without the
    watch a runner that never ends the suite waits for the suite to end by
    itself and then looks like one that did. With a stop_tree that did
    nothing, this test used to pass that way, two minutes late."""
    late = []

    def end_what_is_left():
        pid, child = started(pid_file) or (None, None)
        still = [p for p in (pid, child) if p and alive(p)]
        late.append("run_suite had not come back %ds after the suite's %ds limit%s"
                    % (ENDS_WITHIN, limit, ", and the suite's pytest was still running" if pid in still else ""))
        with rat._RUNNING_LOCK:
            running = [proc.pid for proc in rat._RUNNING]
        for p in running + still:
            end_tree(p)
    watch = threading.Timer(limit + ENDS_WITHIN, end_what_is_left)
    watch.daemon = True
    watch.start()
    try:
        came = rat.run_suite(d, Path(sys.executable), timeout=limit)
    finally:
        watch.cancel()
        watch.join()
    assert not late, late[0]
    return came


def test_a_suite_out_of_time_fails_and_ends_what_it_started(tmp_path):
    # A limit that ran out before the suite's test started proves nothing, so
    # it is tried again with a longer one, and the first run where the test
    # did start is the one judged. Beside a full run on 2026-10-03 a suite's
    # pytest took up to 11.6s to reach its first test, past the 10s this used
    # to allow.
    pid_file = tmp_path / "pid.txt"
    d = suite_with(tmp_path, "sleepy", SLEEPY % {"part": str(tmp_path / "pid.part"), "pid": str(pid_file)})
    for limit in (10, 30, 90):
        out, code, _ = run_watched(d, limit, pid_file)
        assert code == -1 and "timed out after %ds" % limit in out, out
        if pid_file.exists():
            break
    else:
        pytest.fail("the suite's test never started, even in %ds, so this proves nothing" % limit)
    pid, child = started(pid_file)
    pytest_ended, child_ended = gone(pid), gone(child)
    for p, ended in ((pid, pytest_ended), (child, child_ended)):
        if not ended:
            end_tree(p)
    assert pytest_ended, "the stopped suite's pytest is still running"
    assert child_ended, "the process the stopped suite's test started is still running"


def test_a_second_run_waits_for_the_first_ones_lock(tmp_path):
    first, second = rat.RunLock(tmp_path), rat.RunLock(tmp_path)
    assert first.try_take()
    assert not second.try_take()
    assert second.holder()["pid"] == os.getpid()
    first.release()
    assert second.try_take()
    second.release()


HOLDER = """
    import subprocess, sys, time
    sys.path.insert(0, %r)
    import run_all_tests as r
    lock = r.RunLock(%r)
    assert lock.try_take()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    print(child.pid, flush=True)
    time.sleep(120)
    """


def start_holder(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", textwrap.dedent(HOLDER) % (str(REPO / "tools"), str(tmp_path))],
                            stdout=subprocess.PIPE, text=True)
    child = int(proc.stdout.readline())
    return proc, child


def test_the_lock_goes_with_its_process_however_it_ends(tmp_path):
    proc, child = start_holder(tmp_path)
    try:
        assert not rat.RunLock(tmp_path).try_take()
        proc.kill()
        proc.wait(timeout=30)
        # Windows lets go of a dead process's locks soon, not at once.
        lock, end = rat.RunLock(tmp_path), time.time() + 20
        while not lock.try_take():
            assert time.time() < end, "a killed run still held the lock"
            time.sleep(0.5)
        lock.release()
    finally:
        rat.stop_tree(child)


def test_stop_ends_this_checkouts_run_and_what_it_started(tmp_path, capsys):
    proc, child = start_holder(tmp_path)
    try:
        assert rat.stop_earlier(rat.RunLock(tmp_path)) == 0
        assert proc.wait(timeout=30) is not None
        assert gone(child), "the run's own child was left running"
        assert "stopped the run of this checkout" in capsys.readouterr().out
    finally:
        rat.stop_tree(proc.pid)
        rat.stop_tree(child)


def test_a_run_of_the_same_checkout_is_named_not_waited_for(tmp_path, capsys):
    proc, child = start_holder(tmp_path)
    try:
        assert rat.take_turn(rat.RunLock(tmp_path), replace=False) == 3
        assert "--replace" in capsys.readouterr().out
        lock = rat.RunLock(tmp_path)
        assert rat.take_turn(lock, replace=True) is None, "--replace did not take over"
        assert gone(child)
        lock.release()
    finally:
        rat.stop_tree(proc.pid)
        rat.stop_tree(child)


def test_another_checkouts_run_is_left_alone(tmp_path, capsys):
    (tmp_path / "test-run.json").write_text(json.dumps({"pid": 1, "checkout": str(tmp_path / "elsewhere")}),
                                            encoding="utf-8")
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""
        import msvcrt, os, sys, time
        f = open(os.path.join(%r, "test-run.lock"), "a+")
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        print("held", flush=True)
        time.sleep(120)
        """) % str(tmp_path)], stdout=subprocess.PIPE, text=True) if os.name == "nt" else None
    if holder is None:
        pytest.skip("the lock file here is Windows' own")
    try:
        assert holder.stdout.readline().strip() == "held"
        assert rat.stop_earlier(rat.RunLock(tmp_path)) == 1
        assert "left alone" in capsys.readouterr().out
    finally:
        holder.kill()


def test_a_run_inside_a_test_takes_no_lock(fake_run, tmp_path, monkeypatch):
    def must_not_wait(lock, replace):
        raise AssertionError("a run inside a test waited for the machine's lock")
    monkeypatch.setattr(rat, "take_turn", must_not_wait)
    monkeypatch.setattr(rat, "run_suite", lambda d, py, timeout=1800: ("1 passed", 0, []))
    fake_run({"only": tmp_path / "only"})
    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert rat.main(["--jobs", "2"]) == 0


def test_each_run_keeps_its_times_and_writes_them_only_when_asked(fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(rat, "run_suite", lambda d, py, timeout=1800: ("1 passed", 0, []))
    fake_run({"x": tmp_path / "x", "y": tmp_path / "y"}, {"x": 7})
    assert rat.main(["--jobs", "2"]) == 0
    assert set(json.loads((tmp_path / "test-output" / "times.json").read_text())) == {"x", "y"}
    assert json.loads((tmp_path / "times.json").read_text()) == {"x": 7}
    assert rat.main(["--jobs", "2", "--write-times"]) == 0
    assert set(json.loads((tmp_path / "times.json").read_text())) == {"x", "y"}


def test_the_default_is_a_quarter_of_the_processors_at_most_six(monkeypatch):
    monkeypatch.delenv("PAPERPULL_TEST_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 24)
    assert rat.default_jobs() == 6
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert rat.default_jobs() == 1
    monkeypatch.setenv("PAPERPULL_TEST_JOBS", "3")
    assert rat.default_jobs() == 3
