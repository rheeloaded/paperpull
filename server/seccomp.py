"""Make server/seccomp-chrome.json, Docker's default security profile with
the one change Chrome's own sandbox needs.

    python server/seccomp.py            say whether the profile is up to date
    python server/seccomp.py --write    write it

Docker filters the system calls a container may make, and its default
profile (seccomp/moby-default.json, from the moby/profiles project, see
seccomp/README.md) lets a process create new namespaces only when the
container holds CAP_SYS_ADMIN, the capability that would also let it mount
filesystems and much else. Chrome shuts every page it shows inside a user
namespace of its own, and needs exactly that and nothing more.

So here `clone` with namespace flags and `unshare` are allowed for every
process, and everything else is left exactly as Docker ships it. The
container is never given CAP_SYS_ADMIN, so the other calls Docker keeps
behind it stay refused. The experiment ran with the filter switched off
altogether (seccomp=unconfined), which is fine for a test and not for a
container holding signed-in sessions.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent
SOURCE = SERVER / "seccomp" / "moby-default.json"
TARGET = SERVER / "seccomp-chrome.json"
FOR_CHROME = ("clone", "unshare")
COMMENT = "PaperPull Server. Chrome's sandbox makes user namespaces, so these are allowed."


def chrome_profile(default: dict) -> dict:
    """Docker's profile, with clone and unshare allowed for every process.

    Two rules let `clone` through only without namespace flags, one per way
    the architecture orders the arguments, and the rule that allows a set of
    calls to a CAP_SYS_ADMIN holder names `unshare`. Those `clone` rules go
    and the two calls leave that set, so the one rule added here is the only
    one that decides them. A profile laid out any other way is refused
    rather than guessed at."""
    out = copy.deepcopy(default)
    kept, masked_clone, admin_rule = [], 0, None
    for rule in out["syscalls"]:
        names = rule.get("names", [])
        if names == ["clone"] and rule.get("args"):
            masked_clone += 1
            continue
        if (rule.get("includes", {}).get("caps") == ["CAP_SYS_ADMIN"]
                and rule.get("action") == "SCMP_ACT_ALLOW" and "unshare" in names):
            admin_rule = rule
            rule["names"] = [n for n in names if n not in FOR_CHROME]
        kept.append(rule)
    if masked_clone != 2 or admin_rule is None or out.get("defaultAction") != "SCMP_ACT_ERRNO":
        raise SystemExit("Docker's default profile is not laid out the way seccomp.py "
                         "expects, so it was not changed. Read it before updating this.")
    kept.append({"names": list(FOR_CHROME), "action": "SCMP_ACT_ALLOW", "comment": COMMENT})
    out["syscalls"] = kept
    return out


def render(profile: dict) -> str:
    return json.dumps(profile, indent="\t") + "\n"


def expected() -> str:
    return render(chrome_profile(json.loads(SOURCE.read_text(encoding="utf-8"))))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write seccomp-chrome.json")
    args = ap.parse_args(argv)
    want = expected()
    if args.write:
        TARGET.write_text(want, encoding="utf-8", newline="\n")
        print("wrote", TARGET)
        return 0
    if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != want:
        print("seccomp-chrome.json is not what seccomp.py makes, run it with --write")
        return 1
    print("seccomp-chrome.json is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
