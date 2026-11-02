"""Check a running PaperPull Server container, from inside it.

    docker exec paperpull python /opt/paperpull/server/selftest.py

Each line says what was checked and whether it held. It exits 0 only when
every check held.

  chrome     Chrome is in the browser volume and starts
  sandbox    Chrome runs inside its own sandbox, the namespace sandbox (or
             the setuid sandbox in its place, where the kernel has no user
             namespaces) and the seccomp filter both on, which is what the
             container's security profile is for. When it does not, or
             Chrome stops before it opens a window, it says why, a host with
             no user namespaces or no seccomp-bpf (paperpull_core.host_sandbox).
             On a host with no seccomp-bpf, where Chrome would start with
             half its sandbox, Chrome is not started at all
  screen    a Chrome window opens on the virtual screen
  print      a page prints to a PDF, the way every receipt app saves one
  panel      the panel answers, and with the PaperPull icon for the tab
  password   not signed in, the panel sends you to sign in, and its API and
             the browser screen turn you away
  screen     screen sharing answers inside the container, and the panel's
             screen connection refuses a request that is not signed in
  network    the panel answers on the container's own address, and screen
             sharing does not

It opens one Chrome of its own with a throwaway profile, never a
provider's, and closes it before it ends.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHROME = "/usr/bin/google-chrome-stable"
PANEL = "http://127.0.0.1:8765"
results: list = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print("%-8s %s  %s" % (name, "ok  " if ok else "FAIL", detail), flush=True)
    return ok


def chrome_version() -> str:
    out = subprocess.run([CHROME, "--version"], capture_output=True, text=True, timeout=30)
    return (out.stdout or out.stderr).strip()


class NotStarted(RuntimeError):
    """Chrome opened no debugging port. said is everything it wrote."""

    def __init__(self, message: str, said: str):
        super().__init__(message)
        self.said = said


def core():
    """paperpull_core, from the image's own copy."""
    sys.path.insert(0, "/opt/paperpull/core")
    import paperpull_core
    return paperpull_core


def sandbox_problem() -> str:
    """Why this host cannot give Chrome its sandbox, asked before Chrome is
    (paperpull_core.host_sandbox), or "" when nothing stands in its way or
    it cannot be told."""
    try:
        core()
        from paperpull_core import host_sandbox
        return host_sandbox.problem(host_sandbox.check())
    except Exception:
        return ""


def sandbox_refusal() -> str:
    """Why Chrome is not started here at all, a host without the seccomp-bpf
    filter, where it would run with half its sandbox, or "". The same check
    every sign-in asks (paperpull_core.host_sandbox.refuses_chrome)."""
    try:
        core()
        from paperpull_core import host_sandbox
        found = host_sandbox.check()
        if host_sandbox.refuses_chrome(found):
            return host_sandbox.problem(found) or "This host cannot give Chrome its whole sandbox."
    except Exception:
        pass
    return ""


def sandbox_cause(said: str) -> str:
    """Why Chrome did not start, when its sandbox is why, or "". The host's
    own answer names the cause. Without one, Chrome's own words for a
    sandbox that could not start still say it was the sandbox (#110)."""
    problem = sandbox_problem()
    if problem:
        return problem
    try:
        core()
        from paperpull_core.browser import SERVER_NO_SANDBOX
    except Exception:
        return ""
    if any(mark in said for mark in SERVER_NO_SANDBOX):
        return ("Chrome could not start its sandbox, and PaperPull never starts it without "
                "one. The host check found no reason, see \"Chrome does not start\" in SERVER.md.")
    return ""


def start_chrome(profile: Path) -> tuple[subprocess.Popen, str]:
    """Chrome the way the apps' sign-in step starts it, with no flag that
    would turn its sandbox off."""
    said = profile.parent / (profile.name + ".log")
    with open(said, "wb") as err:
        proc = subprocess.Popen(
            [CHROME, "--user-data-dir=%s" % profile, "--remote-debugging-port=0",
             "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
    port_file = profile / "DevToolsActivePort"
    for _ in range(100):
        if port_file.is_file() and port_file.read_text().strip():
            return proc, "http://127.0.0.1:%s" % port_file.read_text().split()[0]
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    wrote = said.read_text(errors="replace")
    tail = [line for line in wrote.splitlines() if line.strip()][-3:]
    raise NotStarted("Chrome did not open a debugging port. It said: %s"
                     % (" | ".join(tail) or "nothing"), wrote)


def browser_checks() -> None:
    from playwright.sync_api import sync_playwright

    refusal = sandbox_refusal()
    if refusal:
        # Chrome would start here with half its sandbox, so it is not
        # started, as no sign-in starts it.
        check("sandbox", False, refusal)
        check("browser", False, "Chrome was not started, since it would run without its "
                                "whole sandbox")
        return
    profile = Path(tempfile.mkdtemp(prefix="selftest-profile-"))
    proc = None
    try:
        proc, url = start_chrome(profile)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(url)
            context = browser.contexts[0]
            page = context.new_page()

            page.goto("chrome://sandbox")
            lines: list = []
            for _ in range(20):    # the page fills itself in a moment after it loads
                text = page.inner_text("body")
                lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
                if any(line.startswith("Seccomp-BPF sandbox") for line in lines):
                    break
                page.wait_for_timeout(250)
            # The layer-1 engine is the namespace sandbox by default, or the
            # setuid (SUID) sandbox where a NAS kernel forbids user namespaces
            # (see "On Synology" in SERVER.md). Both are real sandboxes, "None"
            # is not.
            layer1 = next((line[len("Layer 1 Sandbox"):].strip() for line in lines
                           if line.startswith("Layer 1 Sandbox")), "")
            seccomp = "Seccomp-BPF sandbox Yes" in lines
            whole = layer1 in ("Namespace", "SUID") and seccomp
            detail = "layer 1 %s, seccomp %s" % (layer1 or "OFF", "on" if seccomp else "OFF")
            if not whole:
                problem = sandbox_problem()
                if problem:
                    detail += ". " + problem
            check("sandbox", whole, detail)

            windows = page.evaluate("[window.outerWidth, window.outerHeight]")
            check("screen", windows[0] > 0 and windows[1] > 0,
                  "a window %dx%d on display %s" % (windows[0], windows[1],
                                                     os.environ.get("DISPLAY", "?")))

            # A page of its own, since Chrome's status pages take no content.
            page.goto("about:blank")
            page.set_content("<h1>PaperPull</h1><p>Sample receipt, Total $12.34</p>")
            cdp = context.new_cdp_session(page)
            pdf = base64.b64decode(cdp.send("Page.printToPDF", {})["data"])
            cdp.detach()
            check("print", pdf.startswith(b"%PDF"), "%d bytes" % len(pdf))

            browser.new_browser_cdp_session().send("Browser.close")
    except NotStarted as e:
        # A Chrome that could not start its sandbox opens no port either, so
        # the sandbox line says why before the port is mentioned.
        why = sandbox_cause(e.said)
        if why:
            check("sandbox", False, why)
        check("browser", False, "%s: %s" % (type(e).__name__, e))
    except Exception as e:  # say what broke, then let the summary count it
        check("browser", False, "%s: %s" % (type(e).__name__, e))
    finally:
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def here(*handlers) -> urllib.request.OpenerDirector:
    """An opener for requests to this container, which never go through a
    proxy. urllib's own sends each one through HTTP_PROXY when the
    container's environment has it, and nothing exempts 127.0.0.1."""
    return urllib.request.build_opener(*handlers, urllib.request.ProxyHandler({}))


def status_of(url: str) -> int:
    """The first answer to a request, a redirect not followed."""
    try:
        with here(_NoRedirect).open(url, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def panel_checks() -> None:
    try:
        with here().open(PANEL + "/", timeout=10) as r:
            page, landed = r.read().decode("utf-8", "replace"), r.url
        with here().open(PANEL + "/favicon.ico", timeout=10) as r:
            icon, kind = r.read(), r.headers.get("Content-Type", "")
        check("panel", "<title>PaperPull</title>" in page and icon[:4] == b"\x00\x00\x01\x00",
              "page and tab icon (%s, %d bytes)" % (kind, len(icon)))
        sent_to = urllib.parse.urlsplit(landed).path
        api, screen = status_of(PANEL + "/api/apps"), status_of(PANEL + "/screen")
        check("password", sent_to in ("/login", "/setup") and api == 401 and screen == 303,
              "not signed in, the panel sends you to %s, its API answers %d and the "
              "screen page %d" % (sent_to, api, screen))
    except Exception as e:
        check("panel", False, "%s: %s" % (type(e).__name__, e))


def screen_checks() -> None:
    """The screen sharing server answers inside the container only, and the
    panel's screen connection refuses a request that is not signed in."""
    try:
        with socket.create_connection(("127.0.0.1", 5900), timeout=10) as s:
            banner = s.recv(12)
        handshake = ("GET /screen/websockify HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n"
                     "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                     "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                     "Sec-WebSocket-Version: 13\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", 8765), timeout=10) as s:
            s.sendall(handshake)
            answer = s.recv(200).split(b"\r\n", 1)[0].decode("latin-1")
        check("screen", banner.startswith(b"RFB ") and " 403" in answer,
              "screen sharing answers inside, a stranger's connection gets %r" % answer)
    except Exception as e:
        check("screen", False, "%s: %s" % (type(e).__name__, e))


# What PAPERPULL_HOSTS_ONLY takes for yes, as gui/server_mode.py reads it
# (server/tests/test_selftest_hosts_only.py holds the two together).
HOSTS_ONLY_ON = ("1", "true", "yes", "on")


def answer_of(url: str) -> tuple:
    """The first answer to a request and the start of its body, a redirect
    not followed."""
    try:
        with here(_NoRedirect).open(url, timeout=10) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")


def network_checks() -> None:
    """The panel answers on the container's own network address, the one
    Docker publishes, and the screen sharing server does not. With
    PAPERPULL_HOSTS_ONLY on, the panel answers that address with its
    refusal unless the address is listed, which still shows it listens
    there. A page there with the address not listed means the panel never
    took the setting, and nothing listed means no other device can open it,
    so both fail."""
    try:
        address = socket.gethostbyname(socket.gethostname())
        panel, body = answer_of("http://%s:8765/favicon.ico" % address)
        try:
            socket.create_connection((address, 5900), timeout=3).close()
            vnc = "answers"
        except OSError:
            vnc = "does not answer"
        hosts_only = (os.environ.get("PAPERPULL_HOSTS_ONLY") or "").strip().lower() in HOSTS_ONLY_ON
        if not hosts_only:
            check("network", panel == 200 and vnc == "does not answer",
                  "on %s the panel answers %d and screen sharing %s" % (address, panel, vnc))
            return
        listed = [item for item in re.split(r"[\s,]+", os.environ.get("PAPERPULL_HOSTS") or "")
                  if item]
        if not listed:
            check("network", False, "PAPERPULL_HOSTS_ONLY is on and PAPERPULL_HOSTS lists "
                  "nothing, so no other device can open the panel")
            return
        address_listed = any(address in re.split(r"[/\[\]:]+", item) for item in listed)
        if panel == 400:
            answers = "PAPERPULL_HOSTS_ONLY is on" in body and not address_listed
            how = "%d, refusing an address PAPERPULL_HOSTS_ONLY leaves out" % panel
        else:
            answers = panel == 200 and address_listed
            how = "%d%s" % (panel, "" if address_listed else ", though PAPERPULL_HOSTS_ONLY is on "
                            "and the address is not listed")
        check("network", answers and vnc == "does not answer",
              "on %s the panel answers %s and screen sharing %s" % (address, how, vnc))
    except Exception as e:
        check("network", False, "%s: %s" % (type(e).__name__, e))


HELPER = "/browser/current/opt/google/chrome/chrome-sandbox"


def as_pp() -> None:
    """Chrome refuses to run as root with its sandbox on, and `docker exec`
    starts as root, so the test hands itself to pp, as everything else in
    the container runs, and with no-new-privileges as the entrypoint gives
    it, unless Chrome's setuid helper is in use, which works only through
    its setuid bit."""
    if os.geteuid() == 0:
        try:
            st = os.stat(HELPER)
            setuid_helper = st.st_uid == 0 and bool(st.st_mode & stat.S_ISUID)
        except OSError:
            setuid_helper = False
        os.execvp("setpriv", ["setpriv", "--reuid=pp", "--regid=pp", "--init-groups"]
                  + ([] if setuid_helper else ["--no-new-privs"])
                  + ["env", "HOME=/home/pp", "USER=pp", sys.executable, os.path.abspath(__file__)])


def graphics_check() -> None:
    """Whether the sign-in window draws on a graphics chip. Not having one
    is said, never failed, since many servers have none, but some sites
    refuse a sign-in from a browser without one (Graphics in SERVER.md)."""
    try:
        sys.path.insert(0, "/opt/paperpull/core")
        from paperpull_core.browser import server_gpu
        switches, env = server_gpu()
    except Exception as e:
        check("graphics", True, "could not be read, %s" % type(e).__name__)
        return
    if switches:
        check("graphics", True, "a graphics chip, through Vulkan (%s)"
              % ", ".join(Path(p).name for p in env["VK_ICD_FILENAMES"].split(":")))
    else:
        check("graphics", True, "none, pages are drawn in software, see Graphics in SERVER.md")


def main() -> int:
    as_pp()
    try:
        version = chrome_version()
        check("chrome", version.startswith("Google Chrome"), version)
    except Exception as e:
        check("chrome", False, "%s: %s" % (type(e).__name__, e))
    if results[-1][1]:
        browser_checks()
    graphics_check()
    panel_checks()
    screen_checks()
    network_checks()
    failed = [name for name, ok, _ in results if not ok]
    print(json.dumps({"passed": not failed, "failed": failed}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
