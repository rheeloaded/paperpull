"""Start PaperPull Server the way SERVER.md tells a person to, and check it.

    python server/smoke.py --image paperpull-server:dev

It copies compose.yaml and the container's security profile into a folder
of its own and starts them there with Docker Compose, under a project and
container name of its own, so it can never touch a real installation or
its volumes. Then it does what a person does on the first visit, choosing a
password with the setup code from the container's log, signs in, sets up a
provider, and runs the self-test inside the container. The project is taken
down with its volumes at the end, whatever happened.

Each line says what was checked and whether it held. It exits 0 only when
every check held. The Server image workflow runs it on every change before
an image can be published, and it runs the same way on any computer with
Docker, as long as nothing else there uses port 8765.

Compose is started from another folder than the one holding compose.yaml,
as `docker compose -f server/compose.yaml up -d` would be, so a path in it
that only works from its own folder is found here and not by a person.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SERVER = Path(__file__).resolve().parent
PROJECT = "paperpull-smoke"
CONTAINER = "paperpull-smoke"
PANEL = "http://127.0.0.1:8765"
# The first start downloads Chrome, about 110 MB from Google.
START_LIMIT = 600
CODE_LINE = re.compile(r"^ {4}([A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4})\s*$", re.M)
PROVIDER = "github"

FAILED: list = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    print("%-9s%-6s%s" % (name, "ok" if ok else "FAIL", detail), flush=True)
    if not ok:
        FAILED.append(name)
    return ok


class _Stay(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer to look at here, never one to follow."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_Stay)


def http(method: str, path: str, form=None, body=None, cookie: str = ""):
    """(status, headers, text) of one request to the panel, sent as its own
    page sends it, with the panel's own address as its origin."""
    headers = {"Origin": PANEL}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(PANEL + path, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=30) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def session_of(headers) -> str:
    """The name=value of the cookie a sign-in answer sets, or ''."""
    for value in headers.get_all("Set-Cookie") or []:
        return value.split(";", 1)[0].strip()
    return ""


def docker(*args, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def compose(folder: Path, *args, timeout: int = 300) -> subprocess.CompletedProcess:
    files = ["-f", str(folder / "compose.yaml"), "-f", str(folder / "compose.smoke.yaml")]
    return subprocess.run(["docker", "compose", "-p", PROJECT, *files, *args],
                          cwd=SERVER.parent, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def write_project(folder: Path, image: str) -> None:
    """compose.yaml and the profile as a person copies them, and beside them
    only what keeps this run apart from a real one, its own image, name and
    ids."""
    shutil.copy2(SERVER / "compose.yaml", folder / "compose.yaml")
    shutil.copy2(SERVER / "seccomp-chrome.json", folder / "seccomp-chrome.json")
    (folder / "data").mkdir()
    lines = ["services:", "  paperpull:", "    image: %s" % image,
             "    container_name: %s" % CONTAINER]
    if hasattr(os, "getuid"):
        # The documents belong to whoever runs this, so the folder can be
        # cleaned up afterwards, as a person's would belong to them.
        lines += ["    environment:", '      PUID: "%d"' % os.getuid(),
                  '      PGID: "%d"' % os.getgid()]
    (folder / "compose.smoke.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def running() -> bool:
    """Up, and up since the first start. compose.yaml restarts a container
    that stops, so one that failed can look running again a moment later."""
    r = docker("inspect", "-f", "{{.State.Running}} {{.RestartCount}}", CONTAINER, timeout=30)
    return r.returncode == 0 and r.stdout.split() == ["true", "0"]


def log() -> str:
    r = docker("logs", CONTAINER, timeout=60)
    return r.stdout + r.stderr


def wait_for_panel() -> bool:
    started = time.time()
    while time.time() - started < START_LIMIT:
        if not running():
            return report("panel", False, "the container stopped or restarted before the panel answered")
        try:
            status, _, _ = http("GET", "/login")
            if status in (200, 303):
                return report("panel", True, "answered %d s after the start" % (time.time() - started))
        except OSError:
            pass
        time.sleep(2)
    return report("panel", False, "no answer in %d s" % START_LIMIT)


def first_visit(password: str) -> str:
    """Choose the password the way the first visit does. The session cookie,
    or '' when it did not hold."""
    status, headers, _ = http("GET", "/")
    if not report("gate", status == 303 and headers.get("Location", "").endswith("/setup"),
                  "with no password yet the panel answers %d to %s"
                  % (status, headers.get("Location", "nowhere"))):
        return ""
    status, _, _ = http("GET", "/setup")
    codes = CODE_LINE.findall(log())
    if not report("code", status == 200 and bool(codes),
                  "the setup page answers %d and %s" % (
                      status, "the log holds a setup code" if codes else "the log holds no setup code")):
        return ""
    status, headers, _ = http("POST", "/setup", form={
        "code": codes[-1], "password": password, "again": password})
    cookie = session_of(headers)
    report("setup", status == 303 and bool(cookie),
           "a password chosen with the code from the log, %d and %s"
           % (status, "a session" if cookie else "no session"))
    return cookie


def sign_in(password: str) -> str:
    status, _, _ = http("GET", "/api/providers")
    report("api", status == 401, "not signed in, the API answers %d" % status)
    status, _, _ = http("POST", "/login", form={"password": password + "x"})
    report("wrong", status == 401, "a wrong password answers %d" % status)
    status, headers, _ = http("POST", "/login", form={"password": password})
    cookie = session_of(headers)
    report("sign-in", status == 303 and bool(cookie),
           "the password answers %d with %s" % (status, "a session" if cookie else "no session"))
    return cookie


def set_up_provider(cookie: str) -> None:
    status, _, text = http("GET", "/api/providers", cookie=cookie)
    try:
        answer = json.loads(text)
    except ValueError:
        answer = {}
    report("signed", status == 200 and answer.get("server") is True
           and answer.get("suggested_root") == "/data",
           "signed in, the API answers %d, server %s, folder %s"
           % (status, answer.get("server"), answer.get("suggested_root")))
    # The page may name any folder. On the server every provider goes in
    # the shared folder all the same.
    status, _, text = http("POST", "/api/create", cookie=cookie,
                           body={"root": "/somewhere/else", "providers": [PROVIDER]})
    try:
        made = json.loads(text)
    except ValueError:
        made = {}
    report("provider", status == 200 and made.get("root") == "/data"
           and PROVIDER in (made.get("created") or []),
           "set up %s, %d, in %s" % (PROVIDER, status, made.get("root")))
    r = docker("exec", CONTAINER, "python", "-c",
               "import glob, json; print(json.dumps([json.load(open(p, encoding='utf-8-sig'))"
               ".get('profile_dir') for p in glob.glob('/data/*/config.json')]))", timeout=60)
    try:
        profiles = json.loads(r.stdout)
    except ValueError:
        profiles = []
    report("profile", bool(profiles) and all(str(p).startswith("/profiles/") for p in profiles),
           "its sign-ins go to %s" % (", ".join(map(str, profiles)) or "nowhere"))


def self_test() -> None:
    r = docker("exec", CONTAINER, "python", "/opt/paperpull/server/selftest.py", timeout=600)
    for line in (r.stdout + r.stderr).splitlines():
        print("  " + line, flush=True)
    report("selftest", r.returncode == 0, "the container's own checks, exit %d" % r.returncode)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", default="paperpull-server:dev",
                    help="the image to start, default %(default)s")
    ap.add_argument("--keep", action="store_true",
                    help="leave the project running afterwards, to look at it")
    args = ap.parse_args(argv)
    # The container's log is printed as it is, and a console that cannot
    # show a character in it should not end the run.
    sys.stdout.reconfigure(errors="replace")

    folder = Path(tempfile.mkdtemp(prefix="paperpull-smoke-"))
    password = secrets.token_urlsafe(18)
    try:
        write_project(folder, args.image)
        r = compose(folder, "up", "-d", timeout=600)
        if report("start", r.returncode == 0,
                  "compose up %s" % ("started it" if r.returncode == 0 else "failed")):
            if wait_for_panel():
                if first_visit(password):
                    cookie = sign_in(password)
                    if cookie:
                        set_up_provider(cookie)
                self_test()
        else:
            print(r.stdout + r.stderr, flush=True)
        if FAILED:
            print("\nthe container's log, last lines", flush=True)
            for line in log().splitlines()[-60:]:
                print("  " + line, flush=True)
    finally:
        if args.keep:
            print("left running, take it down with\n  docker compose -p %s down -v" % PROJECT)
        else:
            down = compose(folder, "down", "-v", "--remove-orphans", timeout=300)
            if down.returncode:
                print(down.stdout + down.stderr, flush=True)
            shutil.rmtree(folder, ignore_errors=True)
    print(json.dumps({"passed": not FAILED, "failed": FAILED}), flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
