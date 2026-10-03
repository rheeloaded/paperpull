"""tools/worktree.py gives work a worktree of its own and cleans up after it.

The one thing it must never do is delete the main checkout's virtual
environments. A worktree reaches them through junctions, and removing a
worktree with git alone can follow a junction into what it points at. So
these build a small repository with an origin, environments and a marker
file in each, and check that a removed or landed worktree leaves every
marker where it was, and that landing pushes only a tree whose suite
passed, never while a release is in progress.

On Windows a folder a program is in cannot be deleted, and the shell that
ran land is usually in its worktree. The first real landing went to main
and then exited 1, with the worktree's files deleted around an empty
folder. Those tests start a process working in the worktree, as that
shell was.
"""
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

wt = pytest.importorskip("worktree")

PASS = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "raise SystemExit(1)"]


def git(where, *args):
    r = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)
    main = tmp_path / "main"
    subprocess.run(["git", "clone", "-q", str(origin), str(main)], check=True, capture_output=True)
    git(main, "config", "user.name", "tester")
    git(main, "config", "user.email", "tester@example.invalid")
    (main / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (main / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (main / "app.py").write_text("x = 1\n", encoding="utf-8")
    for venv in (main / "gui" / ".venv", main / "apps" / "alpha" / ".venv"):
        venv.mkdir(parents=True)
        (venv / "keep.txt").write_text("the main checkout's environment\n", encoding="utf-8")
    (main / "apps" / "alpha" / "alpha.py").write_text("y = 2\n", encoding="utf-8")
    (main / "gui" / "app.py").write_text("z = 3\n", encoding="utf-8")
    # Every worktree of the real repository carries the tool, and the
    # command land prints to finish a removal runs the worktree's own copy.
    (main / "tools").mkdir()
    shutil.copy(REPO / "tools" / "worktree.py", main / "tools" / "worktree.py")
    git(main, "add", ".")
    git(main, "commit", "-q", "-m", "base")
    git(main, "branch", "-M", "main")
    git(main, "push", "-q", "-u", "origin", "main")
    monkeypatch.chdir(main)
    return main


def markers(main):
    return [main / "gui" / ".venv" / "keep.txt", main / "apps" / "alpha" / ".venv" / "keep.txt"]


def whole(tree):
    """Nothing deleted, nothing changed, both links still in place."""
    return (git(tree, "status", "--porcelain") == ""
            and all(wt.is_link(tree / rel) for rel in ("gui/.venv", "apps/alpha/.venv")))


def committed_change(world):
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(tree, "commit", "-q", "-am", "change x")
    return tree


@contextmanager
def held(folder, how="shell"):
    """A shell working in the folder, as the one that ran land is, or a
    program with one of its files open."""
    if how == "shell":
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(folder))
        try:
            yield
        finally:
            proc.kill()
            proc.wait()
    else:
        with open(folder / "app.py", encoding="utf-8"):
            yield


WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="only Windows refuses to delete a folder in use")


def test_new_links_each_environment_of_the_main_checkout(world):
    tree = wt.new(world, "feature")
    assert tree == world.parent / "rsd-feature"
    assert git(tree, "rev-parse", "--abbrev-ref", "HEAD") == "feature"
    for rel in ("gui/.venv", "apps/alpha/.venv"):
        assert wt.is_link(tree / rel)
        assert (tree / rel / "keep.txt").exists()
    assert git(tree, "status", "--porcelain") == ""
    # the new branch follows nothing, so a bare push cannot land on main
    assert subprocess.run(["git", "-C", str(tree), "rev-parse", "--abbrev-ref", "@{u}"],
                          capture_output=True).returncode != 0


def test_remove_unlinks_first_and_the_environments_survive(world):
    tree = wt.new(world, "feature")
    wt.remove(world, "feature")
    assert not tree.exists()
    assert all(m.exists() for m in markers(world)), "removing a worktree deleted the main environments"
    assert "feature" not in git(world, "branch", "--list", "feature"), "a merged branch was kept"


def test_a_worktree_with_uncommitted_work_is_left_alone(world):
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        wt.remove(world, "feature")
    assert tree.exists() and wt.is_link(tree / "gui" / ".venv")


def test_a_real_folder_is_never_unlinked(tmp_path):
    real = tmp_path / ".venv"
    real.mkdir()
    with pytest.raises(SystemExit):
        wt.unlink(real)
    assert real.exists()


def test_land_pushes_a_passing_tree_and_removes_the_worktree(world):
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(tree, "commit", "-q", "-am", "change x")
    head = git(tree, "rev-parse", "HEAD")
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS) == 0
    assert git(world, "ls-remote", "origin", "refs/heads/main").split()[0] == head
    assert not tree.exists()
    assert all(m.exists() for m in markers(world))


def test_land_pushes_nothing_when_the_suite_fails(world):
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(tree, "commit", "-q", "-am", "change x")
    before = git(world, "ls-remote", "origin", "refs/heads/main").split()[0]
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=FAIL, ruff_cmd=PASS) == 1
    assert git(world, "ls-remote", "origin", "refs/heads/main").split()[0] == before
    assert tree.exists()


@WINDOWS_ONLY
def test_land_from_a_shell_inside_lands_and_keeps_the_worktree_whole(world, capsys):
    tree = committed_change(world)
    head = git(tree, "rev-parse", "HEAD")
    os.chdir(tree)
    with held(tree):
        assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS) == 0, "a landing read as a failure"
        out = capsys.readouterr().out
        assert git(world, "ls-remote", "origin", "refs/heads/main").split()[0] == head
        assert "landed" in out and "in use" in out and "went through" in out
        assert whole(tree), "the worktree was half deleted around the shell"
        assert all(m.exists() for m in markers(world))
    # Once the shell has gone, the command land printed finishes the job
    # from a folder outside the repository.
    command = out.strip().splitlines()[-1].strip()
    assert command.endswith('remove "%s"' % tree)
    r = subprocess.run(command, cwd=str(world.parent), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not tree.exists()
    assert all(m.exists() for m in markers(world))
    assert git(world, "branch", "--list", "feature") == "", "a landed branch was kept"


@WINDOWS_ONLY
@pytest.mark.parametrize("how", ["shell", "open file"])
def test_remove_leaves_a_worktree_in_use_whole(world, how):
    tree = wt.new(world, "feature")
    with held(tree / "apps" / "alpha" if how == "shell" else tree, how):
        with pytest.raises(SystemExit, match="in use"):
            wt.remove(world, "feature")
        assert whole(tree)
    wt.remove(world, "feature")
    assert not tree.exists()
    assert all(m.exists() for m in markers(world))


def test_a_landing_reads_as_landed_whatever_the_removal_does(world, capsys, monkeypatch):
    tree = committed_change(world)
    head = git(tree, "rev-parse", "HEAD")

    def refuses(where, name_or_path, quiet=False):
        raise SystemExit("git would not remove %s" % name_or_path)

    monkeypatch.setattr(wt, "remove", refuses)
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS) == 0
    out = capsys.readouterr().out
    assert git(world, "ls-remote", "origin", "refs/heads/main").split()[0] == head
    assert "landed" in out and "went through" in out and 'remove "%s"' % tree in out


def test_remove_drops_a_landed_branch_though_the_main_checkout_is_behind(world, capsys):
    tree = committed_change(world)
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS, keep=True) == 0
    # Nobody pulls into the main checkout, so git branch -d alone refuses.
    assert git(world, "rev-parse", "HEAD") != git(tree, "rev-parse", "HEAD")
    os.chdir(world.parent)
    wt.remove(world.parent, str(tree))
    assert not tree.exists()
    assert git(world, "branch", "--list", "feature") == ""
    assert "which main holds" in capsys.readouterr().out


def test_remove_keeps_a_branch_that_is_not_on_main(world, capsys):
    committed_change(world)
    wt.remove(world, "feature")
    assert "feature" in git(world, "branch", "--list", "feature")
    assert "not on main" in capsys.readouterr().out


def test_land_waits_for_a_release(world, capsys):
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(tree, "commit", "-q", "-am", "change x")
    assert wt.release(world, "take", "the 1.1.0 session") == 0
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS) == 1
    assert "release is in progress" in capsys.readouterr().out
    assert wt.release(world, "drop") == 0
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS, keep=True) == 0


def test_the_release_worktree_itself_lands_while_others_wait(world, capsys):
    rel = wt.new(world, "rel")
    (rel / "VERSION").write_text("1.1.0\n", encoding="utf-8")
    git(rel, "commit", "-q", "-am", "Version 1.1.0")
    os.chdir(rel)
    assert wt.release(rel, "take", "the 1.1.0 session") == 0
    other = wt.new(world, "feature")
    (other / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(other, "commit", "-q", "-am", "change x")
    os.chdir(other)
    assert wt.land(other, suite_cmd=PASS, ruff_cmd=PASS) == 1
    os.chdir(rel)
    assert wt.land(rel, suite_cmd=PASS, ruff_cmd=PASS, keep=True) == 0
    assert git(world, "ls-remote", "origin", "refs/heads/main").split()[0] == git(rel, "rev-parse", "HEAD")


def test_land_waits_for_a_worktree_holding_an_unfinished_version(world, capsys):
    other = wt.new(world, "release-work")
    (other / "VERSION").write_text("1.1.0\n", encoding="utf-8")
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(tree, "commit", "-q", "-am", "change x")
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS) == 1
    assert "looks like a release" in capsys.readouterr().out


def test_a_changelog_bullet_in_progress_elsewhere_does_not_hold_a_landing(world):
    other = wt.new(world, "other-work")
    (other / "CHANGELOG.md").write_text("## [Unreleased]\n- a bullet in progress\n", encoding="utf-8")
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    git(tree, "commit", "-q", "-am", "change x")
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS, keep=True) == 0


def test_land_refuses_uncommitted_work(world, capsys):
    tree = wt.new(world, "feature")
    (tree / "app.py").write_text("x = 2\n", encoding="utf-8")
    os.chdir(tree)
    assert wt.land(tree, suite_cmd=PASS, ruff_cmd=PASS) == 1
    assert "uncommitted" in capsys.readouterr().out


def test_list_names_a_worktree_on_unrelated_history(world, capsys):
    tree = world.parent / "rsd-old"
    git(world, "worktree", "add", "-q", "--detach", str(tree))
    git(tree, "checkout", "-q", "--orphan", "old-history")
    git(tree, "commit", "-q", "-m", "before the rewrite")
    wt.describe(world)
    out = capsys.readouterr().out
    assert any("rsd-old" in ln and "OLD HISTORY" in ln for ln in out.splitlines())
