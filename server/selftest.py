"""Check a running PaperPull Server container, from inside it.

    docker exec paperpull python /opt/paperpull/server/selftest.py

Each line says what was checked and whether it held. It exits 0 only when
every check held.

  chrome     Chrome is in the browser volume and starts
  sandbox    Chrome runs inside its own sandbox, the namespace sandbox and
             the seccomp filter both on, which is what the container's
             security profile is for
  screen     a Chrome window opens on the virtual screen
  print      a page prints to a PDF, the way every receipt app saves one
  panel      the panel answers, and with the PaperPull icon for the tab

It opens one Chrome of its own with a throwaway profile, never a
provider's, and closes it before it ends.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    tail = [line for line in said.read_text(errors="replace").splitlines() if line.strip()][-3:]
    raise RuntimeError("Chrome did not open a debugging port. It said: %s"
                       % (" | ".join(tail) or "nothing"))


def browser_checks() -> None:
    from playwright.sync_api import sync_playwright

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
            namespace = "Layer 1 Sandbox Namespace" in lines
            seccomp = "Seccomp-BPF sandbox Yes" in lines
            check("sandbox", namespace and seccomp,
                  "namespace %s, seccomp %s" % ("on" if namespace else "OFF",
                                                "on" if seccomp else "OFF"))

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
    except Exception as e:  # say what broke, then let the summary count it
        check("browser", False, "%s: %s" % (type(e).__name__, e))
    finally:
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def panel_checks() -> None:
    try:
        with urllib.request.urlopen(PANEL + "/", timeout=10) as r:
            page = r.read().decode("utf-8", "replace")
        with urllib.request.urlopen(PANEL + "/favicon.ico", timeout=10) as r:
            icon, kind = r.read(), r.headers.get("Content-Type", "")
        check("panel", "<title>PaperPull</title>" in page and icon[:4] == b"\x00\x00\x01\x00",
              "page and tab icon (%s, %d bytes)" % (kind, len(icon)))
    except Exception as e:
        check("panel", False, "%s: %s" % (type(e).__name__, e))


def as_pp() -> None:
    """Chrome refuses to run as root with its sandbox on, and `docker exec`
    starts as root, so the test hands itself to pp, as everything else in
    the container runs."""
    if os.geteuid() == 0:
        os.execvp("setpriv", ["setpriv", "--reuid=pp", "--regid=pp", "--init-groups",
                              "env", "HOME=/home/pp", "USER=pp", sys.executable,
                              os.path.abspath(__file__)])


def main() -> int:
    as_pp()
    try:
        version = chrome_version()
        check("chrome", version.startswith("Google Chrome"), version)
    except Exception as e:
        check("chrome", False, "%s: %s" % (type(e).__name__, e))
    if results[-1][1]:
        browser_checks()
    panel_checks()
    failed = [name for name, ok, _ in results if not ok]
    print(json.dumps({"passed": not failed, "failed": failed}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
