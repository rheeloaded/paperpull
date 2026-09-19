"""Give a second person their own account in one app, or in every app.

    python tools/add_account.py spouse                   every app under the root
    python tools/add_account.py spouse --app chase       one app
    python tools/add_account.py spouse --owner "Jane Doe" --port-offset 20
    python paperpull.py chase add-account spouse         the same, from the launcher

Each account gets its OWN output folder, browser profile and debugging port,
so progress.json, the CSVs, the PDFs and the sign-in session never mix, and
nothing already downloaded is affected. What comes out is a
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


def make_config(app_dir: Path, name: str, port_offset: int = 10,
                owner: str = "") -> Path | None:
    """Write config.<name>.json for one app. Returns its path, or None when
    the app has no config.json yet (it has not been set up)."""
    base = app_dir / "config.json"
    if not base.is_file():
        return None
    cfg = json.loads(base.read_text(encoding="utf-8-sig"))

    cfg["owner"] = owner or name.title()   # stamped on every document this account downloads
    out = Path(cfg["output_dir"])
    cfg["output_dir"] = str(out.parent / f"{out.name} - {name}")
    cfg["profile_dir"] = str(Path(cfg["output_dir"]) /
                             Path(cfg.get("profile_dir", "browser-profile")).name)
    if cfg.get("cdp_url"):
        m = re.search(r":(\d+)", cfg["cdp_url"])
        if m:
            cfg["cdp_url"] = cfg["cdp_url"].replace(
                m.group(1), str(int(m.group(1)) + port_offset))

    dest = app_dir / f"config.{slug(name)}.json"
    dest.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    return dest


def add_account(app_dirs: list[Path], name: str, port_offset: int = 10,
                owner: str = "") -> list[Path]:
    owner = owner or name.title()
    print(f"Creating '{name}' account configs (holder: {owner}):\n")
    made = []
    for app_dir in app_dirs:
        dest = make_config(app_dir, name, port_offset, owner)
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
    ap.add_argument("--port-offset", type=int, default=10,
                    help="added to each app's debugging port (default 10)")
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
