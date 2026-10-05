"""tools/release_assets.py, what a release carries besides its packages.

The server's setup files come from the release's own tag and nothing else,
every file in the Assets list says what it is for, and the notes end with a
Downloads section once. tools/release.sh uses all three, so a release made
with it looks the way 0.43.0 was put right by hand after it was published.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import release_assets  # noqa: E402

COMPOSE = b"name: paperpull\nservices:\n  paperpull:\n    image: example\n"
PROFILE = b'{"defaultAction": "SCMP_ACT_ERRNO"}\n'


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "-c", "core.autocrlf=false", *args],
                   check=True, capture_output=True)


def tagged_repo(tmp_path):
    """A repo whose tag v9.9.9 holds the server's files, and whose working
    copy has moved on since, as a checkout does between a tag and its
    release."""
    repo = tmp_path / "repo"
    (repo / "server").mkdir(parents=True)
    (repo / "server" / "compose.yaml").write_bytes(COMPOSE)
    (repo / "server" / "seccomp-chrome.json").write_bytes(PROFILE)
    (repo / "server" / "Dockerfile").write_bytes(b"FROM scratch\n")
    (repo / "VERSION").write_bytes(b"9.9.9\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the release")
    git(repo, "tag", "v9.9.9")
    (repo / "server" / "compose.yaml").write_bytes(b"changed after the tag\n")
    return repo


def test_the_server_kit_is_the_tags_two_files_and_a_note(tmp_path):
    repo = tagged_repo(tmp_path)
    out = release_assets.server_kit("9.9.9", tmp_path / "flat", repo=repo)

    assert out == tmp_path / "flat" / "PaperPull-Server-9.9.9.zip"
    with zipfile.ZipFile(out) as z:
        files = {n for n in z.namelist() if not n.endswith("/")}
        assert files == {"PaperPull-Server-9.9.9/compose.yaml",
                         "PaperPull-Server-9.9.9/seccomp-chrome.json",
                         "PaperPull-Server-9.9.9/README.txt"}
        assert z.read("PaperPull-Server-9.9.9/compose.yaml") == COMPOSE, \
            "the tag's compose.yaml, never the working copy's, and with LF endings"
        assert z.read("PaperPull-Server-9.9.9/seccomp-chrome.json") == PROFILE
        note = z.read("PaperPull-Server-9.9.9/README.txt").decode("utf-8")
    assert "https://github.com/rheeloaded/paperpull/blob/v9.9.9/SERVER.md" in note


def test_every_asset_a_release_carries_says_what_it_is_for():
    for name, use in (("PaperPull-1.2.3-setup.exe", "Windows installer"),
                      ("PaperPull-1.2.3.zip", "Windows, no installer"),
                      ("PaperPull-1.2.3-arm64.dmg", "Mac with Apple Silicon"),
                      ("PaperPull-Server-1.2.3.zip", "PaperPull Server setup files")):
        assert release_assets.label(name, "1.2.3") == "%s (%s)" % (use, name)
    assert release_assets.label("SHA256SUMS.txt", "1.2.3") == "SHA256SUMS.txt"
    assert release_assets.label("PaperPull-1.2.2.zip", "1.2.3") == "PaperPull-1.2.2.zip", \
        "another version's file is not taken for this one's"


def test_the_notes_end_with_downloads_once():
    notes = "Release 1.2.3\n\nWhat changed.\n"
    once = release_assets.with_downloads(notes, "1.2.3")
    assert once.startswith(notes.rstrip("\n")) and once.count("## Downloads") == 1
    assert release_assets.with_downloads(once, "1.2.3") == once
    for name in ("PaperPull-1.2.3-setup.exe", "PaperPull-1.2.3.zip",
                 "PaperPull-1.2.3-arm64.dmg", "PaperPull-Server-1.2.3.zip"):
        assert "`%s`" % name in once, name


def test_what_it_writes_keeps_the_house_punctuation():
    text = release_assets.downloads_section("1.2.3") + release_assets.server_readme("1.2.3")
    assert "—" not in text and ";" not in text


def test_release_sh_labels_every_asset_and_adds_the_server_kit_and_downloads():
    script = (REPO / "tools" / "release.sh").read_text(encoding="utf-8")
    assert 'ASSETS_PY="$(pypath "$HERE/tools/release_assets.py")"' in script
    for call in ('"$ASSETS_PY" kit', '"$ASSETS_PY" label', '"$ASSETS_PY" notes'):
        assert call in script, call
    assert '#$label"' in script, "each asset goes up with its label"
    assert '--notes-file "$(winpath "$WORK/notes.md")"' in script, \
        "the release is made from the notes with Downloads at their end"
