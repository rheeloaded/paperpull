"""The PaperPull container runs with no more than it needs.

An outside audit asked for a read-only root and dropped capabilities, which
0.56.0 gave Caddy alone. Both compose files now give the panel's container
no-new-privileges, the seven capabilities its start needs out of Docker's
fourteen, a read-only root and three folders in memory, each measured on
Chrome 155 in Docker Desktop on 2026-10-19 (server/smoke.py checks the same
in a running container).

- CHOWN, DAC_OVERRIDE and FOWNER give pp its folders, as root, and SETUID
  and SETGID hand everything to pp. Without any one the start stopped.
- KILL. Without it the container's init could not pass a stop on to the
  panel ("Unexpected error when forwarding signal") and everything was
  killed at once.
- SYS_CHROOT. The security profile, Docker's own, allows chroot only to a
  container holding it, and Chrome's sandbox chroots, so without it Chrome's
  zygote died at once.
- read_only. The start rewrote /etc/passwd and /etc/group for PUID and PGID,
  which a read-only root refused ("groupmod: cannot lock /etc/group"). They
  are links into /run/paperpull now, written there at every start from the
  image's copies in /etc/paperpull.
- no-new-privileges turns the setuid bit off, so Chrome's setuid sandbox
  cannot start under it, measured with user namespaces refused by a profile
  made for the test. The Synology opt-in takes it out.

Read as text, since the Python that runs this suite may have no YAML parser.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

import smoke  # noqa: E402

KEPT = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "KILL", "SYS_CHROOT"]
ENTRYPOINT = (SERVER / "entrypoint.sh").read_text(encoding="utf-8")
CHROME_SH = (SERVER / "chrome.sh").read_text(encoding="utf-8")
DOCKERFILE = (SERVER / "Dockerfile").read_text(encoding="utf-8")

needs_sh = pytest.mark.skipif(not (shutil.which("sh") and shutil.which("awk")),
                              reason="runs the entrypoint's own shell code")


def panel(name: str) -> list:
    """The lines of the paperpull service in a compose file, comments left
    out."""
    out, inside = [], False
    for line in (SERVER / name).read_text(encoding="utf-8").splitlines():
        if re.match(r"^  [\w-]+:\s*$", line):
            inside = line.strip() == "paperpull:"
            continue
        if inside and line and not line.startswith("    "):
            inside = False
        if inside and line.strip() and not line.strip().startswith("#"):
            out.append(line)
    return out


def block(lines: list, key: str) -> list:
    """The list items under one key of the service."""
    at = lines.index("    %s:" % key)
    items = []
    for line in lines[at + 1:]:
        if not line.startswith("      - "):
            break
        items.append(line[len("      - "):])
    return items


@pytest.mark.parametrize("name", ["compose.yaml", "compose.https.yaml"])
def test_both_compose_files_lock_the_panel_down(name):
    lines = panel(name)
    assert block(lines, "security_opt") == ["seccomp=./seccomp-chrome.json",
                                            "no-new-privileges:true"]
    assert block(lines, "cap_drop") == ["ALL"]
    assert block(lines, "cap_add") == KEPT
    assert "    read_only: true" in lines
    assert block(lines, "tmpfs") == ["/tmp", "/run", "/home/pp"]
    assert "privileged" not in "\n".join(lines)


@pytest.mark.parametrize("name", ["compose.yaml", "compose.https.yaml"])
def test_the_limits_are_examples_that_uncomment_into_valid_keys(name):
    text = (SERVER / name).read_text(encoding="utf-8").splitlines()
    for line in ("    #pids_limit: 2048", "    #mem_limit: 4g"):
        assert text.count(line) == 1, line
        assert line.replace("#", "", 1).startswith("    ") and "  #" not in line.replace("#", "", 1)
    assert "pids_limit" not in "\n".join(panel(name)) and "mem_limit" not in "\n".join(panel(name))


def test_the_smoke_run_looks_up_names_as_a_compose_file_gives_them():
    """user and group_add by name, and docker exec -u root, as a person's
    own compose file or NAS console may use them."""
    source = (SERVER / "smoke.py").read_text(encoding="utf-8")
    assert '"--user", "root", "--group-add", "video"' in source
    assert '"exec", "-u", "root", CONTAINER' in source
    main = source[source.index("def main("):]
    assert main.index("locked_down()") < main.index("names_phase(args.image)")


def test_the_smoke_run_has_chrome_build_its_sandbox_through_the_helper():
    """Docker Desktop's kernel has user namespaces, so Chrome is kept from
    them to show the helper works with the capabilities the container keeps,
    the way a Synology without them needs it (measured in review, layer 1
    SUID with PID and network namespaces and seccomp on). Without a helper
    set up, the same start must fail, or it would prove nothing."""
    assert '"--disable-namespace-sandbox"' in smoke._ONLY_THE_HELPER
    for word in ("--no-sandbox", "--disable-seccomp", "--disable-setuid-sandbox"):
        assert word not in smoke._ONLY_THE_HELPER, word
    source = (SERVER / "smoke.py").read_text(encoding="utf-8")
    phase = source[source.index("def setuid_phase("):source.index("def root_certificate(")]
    assert phase.index('report("nnp-said"') < phase.index('report("nnp-run", said.startswith("did not start")')
    assert phase.index('report("suid-on"') < phase.index(
        'report("suid-run", said == "layer 1 SUID, seccomp Yes, page 42"')


def test_the_smoke_run_checks_what_the_compose_files_keep():
    assert sorted(smoke.KEPT) == sorted(KEPT)
    # The bits of linux/capability.h.
    assert smoke.KEPT == {"CHOWN": 0, "DAC_OVERRIDE": 1, "FOWNER": 3, "KILL": 5, "SETGID": 6,
                          "SETUID": 7, "SYS_CHROOT": 18}
    assert smoke.SYS_ADMIN_BIT == 21
    assert list(smoke.SCRATCH) == block(panel("compose.yaml"), "tmpfs")


def test_nothing_the_start_runs_edits_etc():
    """A read-only root refuses every change under /etc, so the start writes
    the ids into /run/paperpull, where /etc/passwd and /etc/group point."""
    code = "\n".join(line for line in ENTRYPOINT.splitlines() if not line.lstrip().startswith("#"))
    for tool in ("usermod", "groupmod", "groupadd", "useradd", "/etc/passwd", "/etc/group"):
        assert tool not in code, tool
    assert "user_files /etc/paperpull /run/paperpull" in code
    links = DOCKERFILE[DOCKERFILE.index("RUN mkdir -p /etc/paperpull /run/paperpull"):]
    links = links[:links.index("\n\n")]
    assert "cp /etc/passwd /etc/group /etc/paperpull/" in links
    assert "ln -s /run/paperpull/passwd /etc/passwd" in links
    assert "ln -s /run/paperpull/group /etc/group" in links
    # The image's /run keeps copies without pp, where Docker looks up the
    # names a compose file gives it (user, group_add), and where `docker
    # exec -u pp` would otherwise find pp with the image's 1000 rather than
    # PUID. Found missing in review, Docker refused `group_add: - video`.
    for name in ("passwd", "group"):
        written = "grep -v '^pp:' /etc/paperpull/%s >/run/paperpull/%s" % (name, name)
        assert links.index("id pp") < links.index(written) < links.index("! id pp")
    assert links.index("! id pp") < links.index("id root && getent group video")
    assert "rm /run/paperpull" not in links
    # After pp is made, so the copies hold it.
    assert DOCKERFILE.index("useradd --create-home --uid 1000 pp") < DOCKERFILE.index(links)
    # The ids are written before anything asks for pp by name.
    assert code.index("user_files /etc/paperpull") < code.index("-exec chown pp:pp")


GIVE_TO_PP = "find /profiles /config /home/pp -xdev ! -type l \\( -type d -o -links 1 \\) " \
             "-exec chown pp:pp {} +"


def test_the_start_gives_pp_no_file_with_a_second_name():
    """pp could give a file of root's a second name in /home/pp, which an
    older compose file keeps on the image's own file system, and a recursive
    chown then handed root's program to pp, to be run by root at the next
    start (found in review, where fs.protected_hardlinks is 0)."""
    code = "\n".join(line for line in ENTRYPOINT.splitlines() if not line.lstrip().startswith("#"))
    assert GIVE_TO_PP in code.splitlines()
    assert "chown -R" not in code


@pytest.mark.skipif(not (sys.platform.startswith("linux") and hasattr(os, "geteuid")
                         and os.geteuid() == 0 and shutil.which("find")),
                    reason="gives files owners other than this user's, which needs root on Linux")
def test_a_second_name_keeps_its_owner_and_a_link_is_not_followed(tmp_path):
    outside = tmp_path / "image"
    home = tmp_path / "home"
    outside.mkdir()
    home.mkdir()
    program = outside / "chrome.sh"
    program.write_bytes(b"#!/bin/sh\n")
    os.link(program, home / "x")
    os.symlink(program, home / "y")
    (home / "own").write_bytes(b"pp's")
    (home / "folder").mkdir()
    for path in (program, home / "own", home / "folder", home):
        os.chown(path, 0, 0)
    line = GIVE_TO_PP.replace("/profiles /config /home/pp", str(home)).replace("pp:pp", "4242:4242")
    r = subprocess.run(["sh", "-c", line], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert os.stat(program).st_uid == 0 and os.stat(home / "x").st_uid == 0
    assert os.lstat(home / "y").st_uid == 0
    for path in (home, home / "own", home / "folder"):
        assert os.stat(path).st_uid == 4242, path


def test_chrome_sh_keeps_apt_out_of_the_image_and_out_of_tmp():
    assert "APT_DIR=/run/paperpull/apt" in CHROME_SH
    assert "-o Dir::State::Lists=$APT_DIR/lists" in CHROME_SH
    assert "apt-cache policy $APT google-chrome-stable" in CHROME_SH
    assert "APT_LOG=$APT_DIR/apt.log" in CHROME_SH and "chrome-apt.log" not in CHROME_SH


def test_pp_runs_with_no_new_privileges_unless_the_setuid_helper_is_in_use():
    from paperpull_core.host_sandbox import HELPER
    gate = ENTRYPOINT[ENTRYPOINT.index("helper=%s" % HELPER):]
    assert gate.splitlines()[1:3] == [
        "no_new_privs=--no-new-privs",
        'if [ -u "$helper" ] && [ "$(stat -L -c %u "$helper" 2>/dev/null)" = 0 ]; '
        'then no_new_privs=""; fi']
    assert "exec setpriv --reuid=pp --regid=pp --init-groups $no_new_privs env" in gate
    # After chrome.sh, which sets or takes off the bit.
    assert ENTRYPOINT.index("/opt/paperpull/server/chrome.sh") < ENTRYPOINT.index(gate)


def test_what_docker_exec_starts_as_pp_has_no_new_privileges_too():
    from paperpull_core.host_sandbox import HELPER
    selftest = (SERVER / "selftest.py").read_text(encoding="utf-8")
    assert 'HELPER = "%s"' % HELPER in selftest
    assert '([] if setuid_helper else ["--no-new-privs"])' in selftest
    assert "st.st_uid == 0 and bool(st.st_mode & stat.S_ISUID)" in selftest
    reset = (SERVER / "reset_password.py").read_text(encoding="utf-8")
    assert '"--init-groups",\n                              "--no-new-privs", "env"' in reset


def test_the_panel_never_starts_as_root():
    start = (SERVER / "start.sh").read_text(encoding="utf-8")
    refusal = start.index('if [ "$(id -u)" = 0 ]; then')
    assert start[refusal:].splitlines()[2] == "  exit 1"
    assert refusal < start.index("Xvfb :99") < start.index("exec python -m uvicorn")


def test_the_image_has_no_setuid_program():
    strip = DOCKERFILE[DOCKERFILE.index("RUN find / -xdev -type f -perm /6000"):]
    strip = strip[:strip.index("\n\n")]
    assert "-exec chmod ug-s {} +" in strip
    assert 'test -z "$(find / -xdev -type f -perm /6000)"' in strip
    # After the last package is installed, and before the image's own files.
    assert DOCKERFILE.rindex("apt-get install") < DOCKERFILE.index(strip)
    assert DOCKERFILE.index(strip) < DOCKERFILE.index("COPY core /opt/paperpull/core")


def test_chrome_sh_sets_up_no_helper_under_no_new_privileges():
    """Without seccomp first, the reason that cannot be mended, then
    no-new-privileges, asked of the kernel, since the NoNewPrivs line of
    /proc/self/status came only in Linux 4.10."""
    gate = CHROME_SH[CHROME_SH.index("SETUID_SANDBOX=0"):]
    gate = gate[:gate.index("\nfi\n")]
    assert gate.index("if ! kernel_has_seccomp; then") < gate.index("elif no_new_privileges; then")
    assert gate.count("SETUID_SANDBOX=1") == 1
    assert gate.index("elif no_new_privileges; then") < gate.index("  else\n    SETUID_SANDBOX=1")
    assert "from paperpull_core.host_sandbox import no_new_privs" in CHROME_SH
    assert "/proc/self/status" not in CHROME_SH.split("no_new_privileges() {")[1].split("}")[0]


def test_an_older_compose_file_is_this_one_without_the_settings():
    """The smoke run starts the new image with compose.yaml as an older
    release had it, these settings left out and nothing else changed."""
    for name in ("compose.yaml", "compose.https.yaml"):
        text = (SERVER / name).read_text(encoding="utf-8")
        older = smoke.as_older_release(text)
        removed = [line for line in text.splitlines() if line not in older.splitlines()]
        lines = panel_lines(older, "paperpull")
        for gone in ("    cap_drop:", "    cap_add:", "    read_only: true", "    tmpfs:",
                     "      - no-new-privileges:true", "      - SYS_CHROOT", "      - /run"):
            assert gone not in lines, (name, gone)
        assert "      - seccomp=./seccomp-chrome.json" in lines
        assert all(line.startswith(("    cap_", "    read_only", "    tmpfs", "      "))
                   for line in removed), removed
        if name == "compose.https.yaml":
            assert "      - no-new-privileges:true" in panel_lines(older, "proxy")
    assert smoke.as_older_release("services:\n  paperpull:\n") == ""


def panel_lines(text: str, name: str) -> list:
    """Every line of one service, comments included."""
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^  [\w-]+:\s*$", line):
            inside = line.strip() == name + ":"
            continue
        if inside and line and not line.startswith("    "):
            inside = False
        if inside:
            out.append(line)
    return out


# -- the user and group files, run as the entrypoint runs them ----------------------

def functions(script: str) -> str:
    """Every function a script defines, and nothing it runs."""
    out, inside = [], False
    for line in script.splitlines():
        if not inside and re.match(r"^[a-z_]+\(\) \{", line):
            out.append(line)
            inside = not line.rstrip().endswith("}")
        elif inside:
            out.append(line)
            inside = line != "}"
    return "\n".join(out) + "\n"


PASSWD = ("root:x:0:0:root:/root:/bin/bash\n"
          "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
          "pp:x:1000:1000::/home/pp:/bin/sh\n")
GROUP = ("root:x:0:\n"
         "video:x:44:\n"
         "render:x:105:someone\n"
         "users:x:100:\n"
         "pp:x:1000:\n")


def user_files(tmp_path: Path, puid: str, pgid: str, joins: str = "") -> tuple:
    image = tmp_path / "image"
    run = tmp_path / "run"
    image.mkdir(exist_ok=True)
    run.mkdir(exist_ok=True)
    (image / "passwd").write_bytes(PASSWD.encode())
    (image / "group").write_bytes(GROUP.encode())
    body = "set -eu\n" + functions(ENTRYPOINT) + 'PUID="$1"\nPGID="$2"\nuser_files "$3" "$4" "$5"\n'
    r = subprocess.run(["sh", "-c", body, "entrypoint.sh", puid, pgid, str(image), str(run),
                        " " + joins + " "], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return ((run / "passwd").read_bytes().decode(), (run / "group").read_bytes().decode(), run)


@needs_sh
def test_pp_takes_puid_and_pgid_and_nothing_else_changes(tmp_path):
    passwd, group, run = user_files(tmp_path, "1026", "100")
    assert passwd == PASSWD.replace("pp:x:1000:1000:", "pp:x:1026:100:")
    assert group == GROUP.replace("pp:x:1000:", "pp:x:100:")
    assert not list(run.glob("*.new"))
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(run / "passwd").st_mode) == 0o644
        assert stat.S_IMODE(os.stat(run / "group").st_mode) == 0o644


@needs_sh
def test_the_defaults_leave_the_image_files_as_they_are(tmp_path):
    passwd, group, _ = user_files(tmp_path, "1000", "1000")
    assert (passwd, group) == (PASSWD, GROUP)


@needs_sh
def test_pp_joins_each_graphics_group_once_and_a_new_number_gets_its_own(tmp_path):
    passwd, group, _ = user_files(tmp_path, "1000", "1000", "44 105 226 226 1000")
    lines = group.splitlines()
    assert "video:x:44:pp" in lines
    assert "render:x:105:someone,pp" in lines
    assert lines.count("dri226:x:226:pp") == 1
    # pp's own group is its primary one, never a member list or a new group.
    assert "pp:x:1000:" in lines and not any(line.startswith("dri1000:") for line in lines)
    assert "users:x:100:" in lines and "root:x:0:" in lines


@needs_sh
@pytest.mark.parametrize("missing", ["passwd", "group"])
def test_a_step_that_fails_fails_the_start_and_leaves_the_files_in_use(tmp_path, missing):
    """The entrypoint calls user_files inside `if !`, where the shell's set -e
    is off, so each step has to stop it by itself. Otherwise a failed awk
    left an empty user file in use, or a later step that worked hid it."""
    image, run = tmp_path / "image", tmp_path / "run"
    image.mkdir()
    run.mkdir()
    (image / "passwd").write_bytes(PASSWD.encode())
    (image / "group").write_bytes(GROUP.encode())
    (image / missing).unlink()
    for name in ("passwd", "group"):
        (run / name).write_bytes(b"in use\n")
    call = ENTRYPOINT[ENTRYPOINT.index("if ! { mkdir -p /run/paperpull"):]
    call = call[:call.index("\nfi\n") + len("\nfi\n")]
    assert 'user_files /etc/paperpull /run/paperpull "$joins"; }; then' in call
    call = call.replace("/run/paperpull", '"$RUN"').replace("/etc/paperpull", '"$IMAGE"')
    body = ("set -eu\n" + functions(ENTRYPOINT) + 'PUID=1026\nPGID=100\njoins=""\n'
            + 'IMAGE="$1"\nRUN="$2"\n' + call + "echo written\n")
    r = subprocess.run(["sh", "-c", body, "entrypoint.sh", str(image), str(run)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "written" not in r.stdout
    assert "could not write its user's ids" in r.stderr
    assert (run / "passwd").read_bytes() == b"in use\n"
    if missing == "group":
        # passwd.new was made, and never put in place.
        assert (run / "group").read_bytes() == b"in use\n"


@needs_sh
def test_a_second_start_writes_the_same_files(tmp_path):
    first = user_files(tmp_path, "1026", "100", "44 226")[:2]
    assert user_files(tmp_path, "1026", "100", "44 226")[:2] == first


@needs_sh
@pytest.mark.parametrize("puid,pgid,given", [
    ("1026", "100", "1026 100"), ("1000", "10", "1000 10"), ("", "", "1000 1000"),
    ("0001026", "0100", "1026 100"), ("1026", "0", "1026 0"),
    ("4294967294", "4294967294", "4294967294 4294967294"),
    ("10x6", "100", None), ("1026", "users", None), ("1026\\n", "100", None),
    ("-1", "100", None), ("1026:0", "100", None), ("0", "100", None), ("000", "100", None),
    ("4294967295", "100", None), ("1026", "4294967295", None), ("99999999999", "100", None),
    ("1" + "0" * 30, "100", None)])
def test_puid_and_pgid_must_be_ids_linux_gives(puid, pgid, given):
    """awk takes them as they are into the user file, so nothing but an id
    gets that far. A PUID of 0 would run everything as root, and so would
    4294967295, which is -1 to the kernel, so setpriv left the user as it was
    (measured in review). Before, usermod refused 4294967295 and the start
    stopped."""
    head = ENTRYPOINT[ENTRYPOINT.index("plain_id() {"):]
    head = head[:head.index("\nfi\n") + len("\nfi\n")]
    r = subprocess.run(["sh", "-c", "set -eu\n" + head + 'echo "$PUID $PGID"\n'],
                       env=dict(os.environ, PUID=puid, PGID=pgid),
                       capture_output=True, text=True, timeout=60)
    if given:
        assert r.returncode == 0 and r.stdout.strip() == given, r.stderr
    else:
        assert r.returncode == 1 and "PUID must be a number from 1 to 4294967294" in r.stderr
