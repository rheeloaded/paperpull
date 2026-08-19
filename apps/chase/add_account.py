"""Create a second account's config for every receipt/document project.

Each account gets its OWN output folder, browser profile, and debugging port,
so progress.json, the CSVs, the PDFs and the sign-in session never mix.
Nothing already downloaded is affected.

Usage (from any project folder):
    python add_account.py jane
    python add_account.py jane --port-offset 10
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# project folder -> (config filename, base port)
PROJECTS = [
    Path(r"C:\path\to\Receipt and Statement Downloader\Target Receipts"),
    Path(r"C:\path\to\Receipt and Statement Downloader\Walmart Receipts"),
    Path(r"C:\path\to\Receipt and Statement Downloader\Amazon Receipts"),
    Path(r"C:\path\to\Receipt and Statement Downloader\Wealthfront Receipts"),
    Path(r"C:\path\to\Receipt and Statement Downloader\Chase Statements"),
    Path(r"C:\path\to\Receipt and Statement Downloader\Robinhood Statements"),
    Path(r"C:\path\to\Receipt and Statement Downloader\American Express Statements"),
]


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "", name).lower() or "account2"


def make_config(project: Path, name: str, port_offset: int,
                owner: str = "") -> Path | None:
    base = project / "config.json"
    if not base.exists():
        print(f"  skip (no config.json): {project.name}")
        return None
    cfg = json.loads(base.read_text(encoding="utf-8-sig"))

    cfg["owner"] = owner or name.title()   # associate this account's docs with a name
    out = Path(cfg["output_dir"])
    cfg["output_dir"] = str(out.parent / f"{out.name} - {name}")
    cfg["profile_dir"] = str(Path(cfg["output_dir"]) /
                             Path(cfg.get("profile_dir", "browser-profile")).name)
    if cfg.get("cdp_url"):
        m = re.search(r":(\d+)", cfg["cdp_url"])
        if m:
            cfg["cdp_url"] = cfg["cdp_url"].replace(
                m.group(1), str(int(m.group(1)) + port_offset))

    dest = project / f"config.{slug(name)}.json"
    dest.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    print(f"  {project.name}")
    print(f"     config : {dest.name}")
    print(f"     output : {cfg['output_dir']}")
    if cfg.get("cdp_url"):
        print(f"     port   : {cfg['cdp_url']}")
    return dest


def main():
    ap = argparse.ArgumentParser(description="Add a second account to all projects")
    ap.add_argument("name", help="account label, e.g. spouse")
    ap.add_argument("--owner", default="",
                    help="account holder's display name (default: the label, "
                         "capitalized). Stamped on every document this account "
                         "downloads.")
    ap.add_argument("--port-offset", type=int, default=10,
                    help="added to each project's debugging port (default 10)")
    args = ap.parse_args()

    owner = args.owner or args.name.title()
    print(f"Creating '{args.name}' account configs (holder: {owner}):\n")
    made = [make_config(p, args.name, args.port_offset, owner) for p in PROJECTS]
    made = [m for m in made if m]
    print(f"\nDone: {len(made)} config(s).\n")
    label = slug(args.name)
    here = Path(__file__).resolve().parent
    entry = next((p.name for p in list(here.glob("*_docs.py"))
                  + list(here.glob("*_receipts.py"))), "run.py")
    if sys.platform == "win32":
        runner = ".venv" + chr(92) + "Scripts" + chr(92) + "python.exe " + entry
        launcher = "login.bat " + label
    else:
        runner = ".venv/bin/python " + entry
        launcher = "./login.command " + label
    print("To use them, add --config to any command, e.g.:")
    print("  " + runner + " --pilot --config config." + label + ".json")
    print("")
    print("Sign in first with that account's own browser profile/port:")
    print("  " + launcher)
    print("\nYour existing downloads are untouched - the new account writes to")
    print("its own folders, and each account's progress.json is separate.")


if __name__ == "__main__":
    main()
