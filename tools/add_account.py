"""Give a second person their own account in one app, or in every app.

    python tools/add_account.py spouse                   every app under the root
    python tools/add_account.py spouse --app chase       one app
    python tools/add_account.py spouse --owner "Jane Doe" --port-offset 20
    python paperpull.py chase add-account spouse         the same, from the launcher

Each account gets its OWN output folder, browser profile and debugging port,
so progress.json, the CSVs, the PDFs and the sign-in session never mix, and
nothing already downloaded is affected. Its port is the first one from 9400
up that no config beside it names, a range no app comes with, so a provider
set up later never arrives on a person's port. What comes out is a
config.<name>.json beside the app's config.json, which every command then
takes as --config (or as --account through the launcher).

The apps are found the way the launcher finds them, by scanning the root
folder for installs, so there is no list of paths in here to keep current.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paperpull  # noqa: E402  the launcher's app discovery


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "", name).lower() or "account2"


def _port_of(url: str) -> int | None:
    m = re.search(r":(\d+)", url or "")
    return int(m.group(1)) if m else None


# The first debugging port a second person is given. The apps' own ports run
# up from 9222, one each, so a person given their app's port plus 10, as
# this did before, could hold the port of an app set up after them
# (E-ZPass's 9274 plus 10 is Interactive Brokers' 9284). A census
# fails once any app's example reaches this, and paperpull_core.ports, which
# tells a person on a shared port where to move, keeps the same number.
PEOPLE_PORTS = 9400


def ports_in_use(app_dirs) -> set:
    """Every debugging port a config of these apps names, each app's
    config.json and config.example.json and every account's
    config.<name>.json. Two apps on one port attach to each other's browser,
    and so to the wrong account's session."""
    used = set()
    for app_dir in app_dirs:
        for path in Path(app_dir).glob("config*.json"):
            try:
                cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            port = _port_of(cfg.get("cdp_url") if isinstance(cfg, dict) else "")
            if port:
                used.add(port)
    return used


def free_cdp_url(app_dir: Path, cdp_url) -> str | None:
    """cdp_url moved up to a port no install beside app_dir uses, or None
    when its own port is free. The control panel asks this of an install it
    has just made. An app's example port is no other app's, but a second
    person added before PEOPLE_PORTS was given their app's port plus 10,
    moved past only the ports in use then, so it can be the example port of
    an app installed afterwards (E-ZPass's 9274 plus 10 is Interactive
    Brokers' 9284 while IBKR is not installed)."""
    base = _port_of(cdp_url if isinstance(cdp_url, str) else "")
    if not base:
        return None
    here = Path(app_dir).resolve()
    taken = ports_in_use([d for d in paperpull.list_apps(Path(app_dir).parent)
                          if d.resolve() != here])
    if base not in taken:
        return None
    port = base
    while port in taken:
        port += 1
    return re.sub(r":%d\b" % base, ":%d" % port, cdp_url, count=1)


def output_dir_for(app_dir: Path, cfg: dict, name: str) -> str:
    """The output_dir a second person's config gets, from the first
    person's config. Their folder sits beside the first one's, named for the
    account, the way "Amazon Receipts - spouse" sits beside "Amazon
    Receipts". A packaged install keeps its downloads in the install folder
    itself (output_dir "."), so there the new folder is a sibling of the
    install, written as a relative path so the install can still be moved.
    The control panel's import asks this too, to read what may already be
    in that folder before it makes the account."""
    out = Path(cfg.get("output_dir") or ".")
    if (app_dir / out).resolve() == app_dir.resolve():
        return str(Path("..") / f"{app_dir.name} - {name}")
    return str(out.parent / f"{out.name} - {name}")


def make_config(app_dir: Path, name: str, port_offset: int | None = None,
                owner: str = "", taken: set | None = None) -> Path | None:
    """Write config.<name>.json for one app. Returns its path, or None when
    the app has no config.json yet (it has not been set up). The new port is
    the first from PEOPLE_PORTS up that is not in `taken`, which then holds
    it too, so a second account never lands on another app's port, nor on
    the port of an app set up later. Given a `port_offset`, it is the app's
    own port plus that many, moved past `taken`, the rule this used before
    (E-ZPass's 9274 plus 10 was Interactive Brokers' 9284)."""
    base = app_dir / "config.json"
    if not base.is_file():
        return None
    cfg = json.loads(base.read_text(encoding="utf-8-sig"))

    cfg["owner"] = owner or name.title()   # stamped on every document this account downloads
    cfg["output_dir"] = output_dir_for(app_dir, cfg, name)
    # A documents folder is one person's (#102). Copied, the new person's
    # documents would go into the first person's folder, so the new account
    # starts with its documents in its own folder and gets its own setting.
    cfg.pop("documents_dir", None)
    cfg["profile_dir"] = str(Path(cfg["output_dir"]) /
                             Path(cfg.get("profile_dir") or "browser-profile").name)
    base = _port_of(cfg.get("cdp_url"))
    if base:
        # The panel's Add a person asks for one app with no set of its own,
        # so the apps beside it are read here.
        taken = taken if taken is not None else ports_in_use(
            list(paperpull.list_apps(Path(app_dir).parent)) + [app_dir])
        port = PEOPLE_PORTS if port_offset is None else base + port_offset
        while port in taken or port == base:
            port += 1
        taken.add(port)
        cfg["cdp_url"] = re.sub(r":%d\b" % base, ":%d" % port, cfg["cdp_url"], count=1)

    dest = app_dir / f"config.{slug(name)}.json"
    dest.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (app_dir / cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    return dest


def add_account(app_dirs: list[Path], name: str, port_offset: int | None = None,
                owner: str = "") -> list[Path]:
    owner = owner or name.title()
    print(f"Creating '{name}' account configs (holder: {owner}):\n")
    made = []
    # Every port the apps beside these already use, the ones not asked for
    # included, so one app's second account is never another app's port.
    neighbors = paperpull.list_apps(Path(app_dirs[0]).parent) if app_dirs else []
    taken = ports_in_use(list(neighbors) + list(app_dirs))
    for app_dir in app_dirs:
        dest = make_config(app_dir, name, port_offset, owner, taken)
        if not dest:
            print(f"  skip (no config.json, run setup first): {app_dir.name}")
            continue
        cfg = json.loads(dest.read_text(encoding="utf-8"))
        print(f"  {app_dir.name}")
        print(f"     config : {dest.name}")
        print(f"     output : {cfg['output_dir']}")
        if cfg.get("cdp_url"):
            print(f"     port   : {cfg['cdp_url']}")
        made.append(dest)
    print(f"\nDone: {len(made)} config(s).")
    if made:
        label = slug(name)
        first = paperpull._slug(app_dirs[0]) or "<app>"
        print("\nSign in with that account's own browser profile and port, then run:")
        print(f"  python paperpull.py {first} login --account {label}")
        print(f"  python paperpull.py {first} pilot --account {label}")
        print("\nExisting downloads are untouched. The new account writes to its own")
        print("folders, and each account's progress.json is separate.")
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Add a second account to one app or every app")
    ap.add_argument("name", help="account label, e.g. spouse")
    ap.add_argument("--app", metavar="APP",
                    help="one app (folder name, slug or provider); default is every app")
    ap.add_argument("--root", metavar="DIR", help="folder holding the apps")
    ap.add_argument("--owner", default="",
                    help="account holder's display name (default: the label, capitalized)")
    ap.add_argument("--port-offset", type=int, default=None,
                    help="give each account its app's debugging port plus this many, moved "
                         "past any port another app or account uses, in place of the first "
                         "free port from %d up" % PEOPLE_PORTS)
    args = ap.parse_args(argv)

    root = paperpull.apps_root(args.root)
    if args.app:
        app_dirs = [paperpull.find_app(root, args.app)]
    else:
        app_dirs = paperpull.list_apps(root)
        if not app_dirs:
            print("No apps under %s" % root)
            return 1
    add_account(app_dirs, args.name, args.port_offset, args.owner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
