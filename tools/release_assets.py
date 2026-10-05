"""What a release carries besides its packages, for tools/release.sh.

    python tools/release_assets.py kit 0.44.0 <folder>           PaperPull-Server-0.44.0.zip there
    python tools/release_assets.py label <file name> 0.44.0      the label the Assets list shows
    python tools/release_assets.py notes 0.44.0 <notes> <out>    the notes, ending with Downloads

PaperPull Server has no package of its own. The Server image workflow
publishes its image to GitHub's container registry when the release is
published, and what a person needs besides is compose.yaml and the security
profile beside it. So the release carries those two as a zip, taken from the
release's own tag and nothing else, with a note on where the setup guide is.

Every file in the Assets list carries a label that says what it is for, and
the notes end with a Downloads section that says the same at more length,
unless they already have one. 0.43.0 got all three by hand after it was
published, and these keep every later release the same.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# What the server's setup needs from the repo, all of it in server/.
SERVER_FILES = ("compose.yaml", "seccomp-chrome.json")


def server_kit_name(version: str) -> str:
    return "PaperPull-Server-%s.zip" % version


def server_readme(version: str) -> str:
    return ("PaperPull Server %s, beta\n"
            "\n"
            "Put compose.yaml and seccomp-chrome.json in a folder of their own on the\n"
            "machine that will run PaperPull Server, fill in compose.yaml, and start it.\n"
            "The image downloads itself the first time. The setup guide walks through\n"
            "every step, a UGREEN NAS included.\n"
            "\n"
            "https://github.com/rheeloaded/paperpull/blob/v%s/SERVER.md\n" % (version, version))


def server_kit(version: str, out_dir, repo=REPO) -> Path:
    """PaperPull-Server-<version>.zip in out_dir. A folder of that name holds
    compose.yaml and seccomp-chrome.json exactly as the tag v<version> has
    them, LF endings and all, whatever the working copy holds, and a
    README.txt that points to the setup guide."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / server_kit_name(version)
    prefix = "PaperPull-Server-%s/" % version
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.txt"
        readme.write_text(server_readme(version), encoding="utf-8", newline="\n")
        # A Windows checkout's core.autocrlf would hand the files over with
        # CRLF, and the files are for a Linux machine.
        subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "archive",
                        "--format=zip", "--prefix=" + prefix, "--add-file=" + str(readme),
                        "-o", str(out), "v%s:server" % version, *SERVER_FILES],
                       check=True)
    return out


def label(name: str, version: str) -> str:
    """What the Assets list shows for a file, what it is for and then its
    name, since the name is still what downloads. A file not known here
    keeps its name."""
    uses = {"PaperPull-%s-setup.exe" % version: "Windows installer",
            "PaperPull-%s.zip" % version: "Windows, no installer",
            "PaperPull-%s-arm64.dmg" % version: "Mac with Apple Silicon",
            server_kit_name(version): "PaperPull Server setup files"}
    use = uses.get(name)
    return "%s (%s)" % (use, name) if use else name


def downloads_section(version: str) -> str:
    return ("## Downloads\n"
            "\n"
            "- **Windows**, `PaperPull-{v}-setup.exe`. The installer, with no admin rights "
            "and no Python needed. It also runs on Windows on ARM.\n"
            "- **Windows without an installer**, `PaperPull-{v}.zip`. The same program as "
            "a folder you unzip anywhere.\n"
            "- **Mac**, `PaperPull-{v}-arm64.dmg`. For Macs with Apple Silicon, signed and "
            "notarized.\n"
            "- **PaperPull Server**, `PaperPull-Server-{v}.zip`. The two setup files the "
            "guide asks for. The server itself downloads from "
            "`ghcr.io/rheeloaded/paperpull-server` when you start it.\n"
            "- **Source code**, the two archives GitHub adds, for running PaperPull from "
            "source on Linux or anywhere else.\n").format(v=version)


def with_downloads(notes: str, version: str) -> str:
    """The notes, ending with the Downloads section unless they have one."""
    if "## Downloads" in notes:
        return notes
    return notes.rstrip("\n") + "\n\n" + downloads_section(version)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 3 and args[0] == "kit":
        print(server_kit(args[1], args[2]))
    elif len(args) == 3 and args[0] == "label":
        print(label(args[1], args[2]))
    elif len(args) == 4 and args[0] == "notes":
        notes = Path(args[2]).read_text(encoding="utf-8")
        Path(args[3]).write_text(with_downloads(notes, args[1]), encoding="utf-8", newline="\n")
    else:
        print("\n".join(__doc__.splitlines()[2:5]), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
