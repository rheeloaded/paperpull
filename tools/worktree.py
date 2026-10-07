"""Give a piece of work its own worktree, land it, and clean up after it.

    python tools/worktree.py new <name>       a worktree beside this checkout
    python tools/worktree.py land             rebase, the suites it touches, push to main, remove
    python tools/worktree.py land --full      the same with the whole suite
    python tools/worktree.py remove <name>    unlink its venvs, remove it, drop its branch
                                              (or the worktree's path, from any folder)
    python tools/worktree.py list             every worktree and what is left in it
    python tools/worktree.py release take <who> | drop | show

WHY

Several sessions work in this repository at once. When they shared one
checkout, one swept another's unfinished files into its commit, a release
was cut with half-done work in it, and every commit started with checking
who else had touched the tree. Each piece of work now gets a worktree of its
own, on a branch cut from origin/main, and nothing else edits it.

A worktree has no virtual environments of its own, and building twenty of
them takes a long time, so new links each .venv of the main checkout into
the new worktree as a junction. Those links are why remove exists. git
worktree remove can follow a junction and delete what it points at, the
main checkout's environments, so remove unlinks every junction first and
only then removes the worktree. Landed worktrees used to be left behind,
sixteen of them by October 2026, three on the history from before the
rewrite of 2026-09-30, so land removes its own when it is done.

Windows will not delete a folder while a program works in it or holds one
of its files open, and the shell that ran land is usually working in its
worktree. The first real landing (2026-10-03) went to main, then git
worktree remove deleted every file, failed on the folder and kept the
branch, and land exited 1 as though nothing had landed. So remove first
renames the worktree away and back, which fails in exactly the cases where
deleting would and changes nothing, and leaves a folder in use whole. A
landing that went through is reported as landed whatever happens after
it, with the command that removes the worktree from outside. A branch
whose commits are all on origin/main is dropped even when the main
checkout is behind, which git branch -d alone would refuse.

LANDING

land refuses a worktree with uncommitted changes, waits for nothing and
stops when a release is in progress (release take, or another worktree
holding an unfinished VERSION), rebases onto a freshly
fetched origin/main, runs the suites of what the branch changes and ruff
on exactly that tree, and pushes it to main. The push runs the pre-push
hook, which checks what it adds against the real records. When main moved
during the suites, the push is refused and land says to run it again,
since a tree nobody tested must not go out.

The whole suite runs before each release, on the release's own tree, and
CI runs it on every push to main (since 2026-10-07, at most one release a
day). It used to run on every landing too, about half an hour each behind
one lock on this machine, and a busy evening queued half a dozen of them.
So a landing runs the suites that test what it changes, an app's own for a
file under apps/<name>, the core's for the core and for tools, whose tests
are in the core's, and the panel's and the server's for theirs, and --full
runs every one. What a landing does not run, CI runs on its push, so land
says which run to watch, and it will not land on a main whose newest
finished Tests run failed, since a second change on a red main hides which
one broke it. --onto-red lands the change that mends it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RELEASE_LOCK = "paperpull-release.json"

# How a finished Tests run on main ends when main is red.
RED = ("failure", "timed_out", "cancelled", "startup_failure")


def git(where, *args, check=False):
    r = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("git %s failed\n%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r


def common_dir(where) -> Path:
    out = git(where, "rev-parse", "--path-format=absolute", "--git-common-dir", check=True).stdout.strip()
    return Path(out)


def main_checkout(where) -> Path:
    return common_dir(where).parent


def venvs_of(checkout: Path) -> list:
    """Each .venv folder of a checkout, as a path relative to it."""
    out = []
    for parent in [checkout / "gui"] + sorted(p for p in (checkout / "apps").glob("*") if p.is_dir()):
        if (parent / ".venv").is_dir() and not is_link(parent / ".venv"):
            out.append((parent / ".venv").relative_to(checkout))
    return out


def is_link(p: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return p.is_symlink() or bool(isjunction and isjunction(p))


def link(src: Path, dst: Path) -> None:
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(src), str(dst))
    else:
        os.symlink(src, dst, target_is_directory=True)


def unlink(p: Path) -> None:
    """Remove a junction or a symlink and never what it points at."""
    if not is_link(p):
        raise SystemExit("%s is a real folder, not a link, so it was left alone" % p)
    if p.is_symlink() and os.name != "nt":
        p.unlink()
    else:
        os.rmdir(p)


def links_in(tree: Path) -> list:
    out = []
    for parent in [tree / "gui"] + sorted(p for p in (tree / "apps").glob("*") if p.is_dir()):
        if is_link(parent / ".venv"):
            out.append(parent / ".venv")
    return out


def path_for(where, name: str) -> Path:
    return main_checkout(where).parent / ("rsd-" + name)


def new(where, name: str) -> Path:
    main = main_checkout(where)
    tree = path_for(where, name)
    if tree.exists():
        raise SystemExit("%s already exists" % tree)
    git(main, "fetch", "--quiet", "origin", check=True)
    git(main, "worktree", "add", "--quiet", "--no-track", "-b", name, str(tree), "origin/main", check=True)
    made = 0
    for rel in venvs_of(main):
        dst = tree / rel
        if dst.parent.is_dir() and not dst.exists():
            link(main / rel, dst)
            made += 1
    print("worktree %s on branch %s from origin/main, %d environments linked" % (tree, name, made))
    return tree


def in_use(tree: Path) -> bool:
    """Whether a program works in the folder or holds one of its files open.

    Windows will not delete such a folder, and git worktree remove then
    deletes what it can and stops, after the links are already gone.
    Renaming the folder fails in exactly those cases, so it is renamed away
    and back, which changes nothing. A link inside it that points at a
    folder in use elsewhere does not count. Other systems delete a folder
    in use, so there it never is. A scanner that holds a file for a moment
    is waited out, a shell working in the folder is not.
    """
    if os.name != "nt":
        return False
    away = tree.with_name("%s.in-use-check-%d" % (tree.name, os.getpid()))
    for attempt in range(5):
        try:
            os.rename(tree, away)
            break
        except PermissionError:
            if attempt == 4:
                return True
            time.sleep(0.5)
        except OSError as e:
            raise SystemExit("could not tell whether %s is in use (%s), so it was left whole" % (tree, e))
    try:
        os.rename(away, tree)
    except OSError as e:
        raise SystemExit("%s was renamed to %s to see whether it was in use and could not be "
                         "renamed back (%s). Rename it back by hand." % (tree, away, e))
    return False


def drop_branch(main: Path, branch: str) -> bool:
    """Delete a branch whose commits are all on main. git branch -d judges
    by the main checkout's own branch, which falls behind origin/main when
    the main checkout is left alone, so a landed branch is judged by
    origin/main as well."""
    if git(main, "branch", "-d", branch).returncode == 0:
        return True
    if git(main, "merge-base", "--is-ancestor", branch, "origin/main").returncode == 0:
        return git(main, "branch", "-D", branch).returncode == 0
    return False


def remove_command(tree: Path) -> str:
    """The command that removes the worktree, run from any folder outside it."""
    return '"%s" "%s" remove "%s"' % (Path(sys.executable).resolve(), tree / "tools" / "worktree.py", tree)


def remove(where, name_or_path: str, quiet=False) -> None:
    tree = Path(name_or_path)
    if not tree.is_absolute():
        tree = path_for(where, name_or_path)
    if not tree.exists():
        raise SystemExit("no worktree at %s" % tree)
    if not (tree / ".git").exists():
        raise SystemExit("%s is not a worktree, it has no .git" % tree)
    # Found from the worktree itself, so remove works from any folder.
    main = main_checkout(tree)
    if os.path.normcase(str(tree.resolve())) == os.path.normcase(str(main.resolve())):
        raise SystemExit("that is the main checkout, which is never removed")
    branch = git(tree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    dirty = git(tree, "status", "--porcelain", "--untracked-files=normal").stdout.strip()
    if dirty:
        raise SystemExit("%s has uncommitted changes, so it was left alone\n%s" % (tree, dirty[:800]))
    if in_use(tree):
        raise SystemExit("%s is in use, by a shell working in it or a program with one of its "
                         "files open, so it was left whole" % tree)
    for p in links_in(tree):
        unlink(p)
    r = git(main, "worktree", "remove", str(tree))
    if r.returncode != 0:
        raise SystemExit("git would not remove %s\n%s" % (tree, (r.stderr or r.stdout).strip()))
    said = "removed %s" % tree
    if branch and branch != "HEAD":
        if drop_branch(main, branch):
            said += ", and its branch %s, which main holds" % branch
        else:
            said += ", and kept its branch %s, which is not on main" % branch
    if not quiet:
        print(said)


def same_tree(a, b) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def release_lock_path(where) -> Path:
    return common_dir(where) / RELEASE_LOCK


def release(where, action: str, who: str = "") -> int:
    path = release_lock_path(where)
    if action == "take":
        if path.exists():
            print("a release is already in progress, %s" % path.read_text(encoding="utf-8").strip())
            return 1
        tree = git(where, "rev-parse", "--show-toplevel").stdout.strip()
        path.write_text(json.dumps({"who": who or "someone", "since": time.strftime("%Y-%m-%d %H:%M"),
                                    "tree": tree}), encoding="utf-8")
        print("release in progress, landing on main waits until release drop, "
              "except from this worktree, which lands the release itself")
        return 0
    if action == "drop":
        if path.exists():
            path.unlink()
        print("no release in progress")
        return 0
    print(path.read_text(encoding="utf-8").strip() if path.exists() else "no release in progress")
    return 0


def release_in_progress(where, tree: Path) -> str:
    """Why landing must wait now, or an empty string."""
    path = release_lock_path(where)
    if path.exists():
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            held = {}
        # The worktree that took the lock lands the release itself.
        if not (held.get("tree") and same_tree(held["tree"], tree)):
            return "a release is in progress, %s" % path.read_text(encoding="utf-8").strip()
    for other in worktrees(where):
        if os.path.normcase(str(other["path"])) == os.path.normcase(str(tree)):
            continue
        # A worktree on the history from before the rewrite cannot be
        # releasing what is on main now.
        if not other["path"].exists() or not git(where, "merge-base", other.get("head", "HEAD"),
                                                 "origin/main").stdout.strip():
            continue
        # Only a release changes VERSION. A changelog bullet in progress is
        # ordinary work and must not hold everyone else's landing.
        busy = git(other["path"], "status", "--porcelain", "--", "VERSION").stdout.strip()
        if busy and other["path"].exists():
            return "%s has an unfinished VERSION, which looks like a release" % other["path"]
    return ""


def worktrees(where) -> list:
    out, cur = [], {}
    for ln in git(where, "worktree", "list", "--porcelain").stdout.splitlines():
        if ln.startswith("worktree "):
            cur = {"path": Path(ln[len("worktree "):])}
            out.append(cur)
        elif ln.startswith("branch "):
            cur["branch"] = ln[len("branch refs/heads/"):]
        elif ln.startswith("HEAD "):
            cur["head"] = ln[len("HEAD "):]
    return out


def describe(where) -> None:
    main = main_checkout(where)
    for wt in worktrees(where):
        p = wt["path"]
        if not p.exists():
            print("%-48s gone from disk, git worktree prune will forget it" % p)
            continue
        head = wt.get("head", "")
        notes = []
        if not git(main, "merge-base", head, "origin/main").stdout.strip():
            notes.append("ON THE OLD HISTORY, never push it")
        elif git(main, "merge-base", "--is-ancestor", head, "origin/main").returncode == 0:
            notes.append("on main already")
        else:
            ahead = git(main, "rev-list", "--count", "origin/main..%s" % head).stdout.strip()
            notes.append("%s commits not on main" % ahead)
        if git(p, "status", "--porcelain").stdout.strip():
            notes.append("uncommitted changes")
        if os.path.normcase(str(p)) == os.path.normcase(str(main)):
            notes.append("the main checkout")
        print("%-48s %-28s %s" % (p, wt.get("branch", "(detached)"), ", ".join(notes)))


def suites_for(tree: Path, changed) -> list:
    """The suites that test what a change touches, by the files it changes,
    in the order first met. Every other suite runs on CI, on the push."""
    names = []
    for path in changed:
        parts = path.replace("\\", "/").split("/")
        if parts[0] == "apps" and len(parts) > 2:
            name = parts[1] if (tree / "apps" / parts[1] / "tests").is_dir() else ""
        elif parts[0] in ("core", "tools"):
            name = "core"
        elif parts[0] in ("gui", "server") and len(parts) > 1:
            name = parts[0]
        else:
            name = ""
        if name and name not in names:
            names.append(name)
    return names


def main_is_red(tree: Path) -> str:
    """Why nothing should land on main now, from the newest finished Tests
    run of a push to it, or "" when that run passed or nobody can say."""
    origin = git(tree, "remote", "get-url", "origin").stdout.strip()
    if "github.com" not in origin:
        return ""
    try:
        r = subprocess.run(["gh", "run", "list", "--workflow", "Tests", "--branch", "main",
                            "--limit", "10", "--json", "status,conclusion,event,url"],
                           cwd=tree, capture_output=True, text=True, timeout=60)
        runs = json.loads(r.stdout or "[]") if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        runs = None
    if not isinstance(runs, list):
        print("GitHub could not be asked how main's last Tests run ended, so this lands "
              "without knowing", flush=True)
        return ""
    done = [x for x in runs if isinstance(x, dict) and x.get("status") == "completed"
            and x.get("event") == "push"]
    if done and done[0].get("conclusion") in RED:
        return "main's newest finished Tests run ended %s, %s" % (done[0]["conclusion"],
                                                                 done[0].get("url", ""))
    return ""


def land(where, suite_cmd=None, ruff_cmd=None, keep=False, full=False, onto_red=False,
         red=main_is_red, runner_cmd=None) -> int:
    tree = Path(git(where, "rev-parse", "--show-toplevel", check=True).stdout.strip())
    main = main_checkout(where)
    if os.path.normcase(str(tree.resolve())) == os.path.normcase(str(main.resolve())):
        print("land works from a worktree of its own, not the main checkout")
        return 1
    if git(tree, "status", "--porcelain").stdout.strip():
        print("commit or drop the uncommitted changes first, land tests exactly what is committed")
        return 1
    why = release_in_progress(where, tree)
    if why:
        print("not landing now, %s. Land after its tag." % why)
        return 1
    git(tree, "fetch", "--quiet", "origin", check=True)
    r = git(tree, "rebase", "origin/main")
    if r.returncode != 0:
        git(tree, "rebase", "--abort")
        print("the rebase onto origin/main stopped on a conflict and was undone\n%s"
              % (r.stdout + r.stderr).strip()[-1500:])
        return 1
    tested = git(tree, "rev-parse", "HEAD", check=True).stdout.strip()
    why = "" if onto_red else red(tree)
    if why:
        print("not landing on a red main, %s. Mend it first, or land the change that mends "
              "it with --onto-red." % why)
        return 1
    py = str(main / "gui" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    runner_cmd = runner_cmd or [py, "tools/run_all_tests.py"]
    ruff_cmd = ruff_cmd or [py, "-m", "ruff", "check", "."]
    if suite_cmd:
        print("running the suite on %s" % tested[:9], flush=True)
    elif full:
        suite_cmd = list(runner_cmd)
        print("running the whole suite on %s" % tested[:9], flush=True)
    else:
        changed = git(tree, "diff", "--name-only", "origin/main...HEAD").stdout.splitlines()
        names = suites_for(tree, changed)
        if names:
            suite_cmd = list(runner_cmd) + ["--suites", ",".join(names)]
            print("running the suites this changes, %s, on %s. CI runs every suite on the push."
                  % (", ".join(names), tested[:9]), flush=True)
        else:
            print("no suite tests what this changes, so ruff alone runs on %s. CI runs every "
                  "suite on the push." % tested[:9], flush=True)
    if suite_cmd and subprocess.run(suite_cmd, cwd=tree).returncode != 0:
        print("the suite did not pass, nothing was pushed")
        return 1
    if subprocess.run(ruff_cmd, cwd=tree).returncode != 0:
        print("ruff found something, nothing was pushed")
        return 1
    if git(tree, "rev-parse", "HEAD").stdout.strip() != tested:
        print("the branch moved while the suite ran, so what passed is not what would go out")
        return 1
    push = subprocess.run(["git", "-C", str(tree), "push", "origin", "HEAD:main"])
    if push.returncode != 0:
        print("the push was refused. If main moved during the suite, run land again, "
              "and if the pre-push check stopped it, look at each line it named.")
        return 1
    print("landed %s on main. Its Tests run on CI is the rest of the check. Find it with\n"
          "  gh run list --workflow Tests --branch main --limit 1\n"
          "and watch it with gh run watch <id>. A red one is mended before anything else lands."
          % tested[:9], flush=True)
    if not keep:
        os.chdir(main)
        try:
            remove(main, str(tree))
        except (SystemExit, OSError) as e:
            # What is on main is on main. A worktree left behind is tidying,
            # and must never make a landing read as a failure.
            print("%s\nThe landing itself went through. To remove the worktree once nothing is "
                  "in it, run this from any folder outside it\n  %s" % (e, remove_command(tree)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action", required=True)
    n = sub.add_parser("new")
    n.add_argument("name")
    r = sub.add_parser("remove")
    r.add_argument("name")
    la = sub.add_parser("land")
    la.add_argument("--keep", action="store_true", help="leave the worktree after landing")
    la.add_argument("--full", action="store_true",
                    help="run the whole suite, not only the suites the change touches")
    la.add_argument("--onto-red", action="store_true",
                    help="land although main's newest Tests run failed, for the change that mends it")
    sub.add_parser("list")
    rel = sub.add_parser("release")
    rel.add_argument("what", choices=["take", "drop", "show"])
    rel.add_argument("who", nargs="?", default="")
    args = ap.parse_args(argv)
    where = Path.cwd()
    if args.action == "new":
        new(where, args.name)
        return 0
    if args.action == "remove":
        remove(where, args.name)
        return 0
    if args.action == "land":
        return land(where, keep=args.keep, full=args.full, onto_red=args.onto_red)
    if args.action == "list":
        describe(where)
        return 0
    return release(where, args.what, args.who)


if __name__ == "__main__":
    sys.exit(main())
