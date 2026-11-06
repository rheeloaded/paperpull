"""PaperPull.app opens its own window. It does not open Terminal.

The bundle's main executable used to be a dozen lines of C that ran
`open -a Terminal` on Resources/paperpull-panel.sh. It is now
packaging/macos/launcher.m, Objective-C that starts the panel as a child
process and shows it in a WKWebView, and packaging/build_macos.py compiles
it. The two are written to one contract, and this holds the build side and
the source's side of it to each other, because the launcher cannot be run
on the machines that run these tests:

    clang -fobjc-arc -O2 -arch <ARCH> -mmacosx-version-min=<MACOS_MIN>
          -framework Cocoa -framework WebKit
          -o Contents/MacOS/PaperPull packaging/macos/launcher.m

The plist carries NSAppTransportSecurity with NSAllowsLocalNetworking, or
WKWebView refuses http://127.0.0.1. The source reads PAPERPULL_PORT (a port
for tests) and PAPERPULL_LAUNCHER_SELFTEST ("ready" and "window"), which the
release workflow's own-executable steps use: "ready" is the hard gate, and
"window" is allowed to fail on a runner with no display. The window itself is
looked at by hand and by that second step, not here.
"""
import importlib.util
import os
import plistlib
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# bm.subprocess is the real module, which _record_commands() replaces run() on
# for the length of a test, so the script tests keep the real one.
REAL_RUN = subprocess.run

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "packaging" / "macos" / "launcher.m"
WORKFLOW = REPO / ".github" / "workflows" / "build-macos.yml"


@pytest.fixture()
def bm(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "bm_native_launcher", REPO / "packaging" / "build_macos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    dist = tmp_path / "dist"
    app = dist / "PaperPull.app"
    monkeypatch.setattr(mod, "DIST", dist)
    monkeypatch.setattr(mod, "APP", app)
    monkeypatch.setattr(mod, "CONTENTS", app / "Contents")
    monkeypatch.setattr(mod, "RES", app / "Contents" / "Resources")
    monkeypatch.setattr(mod, "MACOS", app / "Contents" / "MacOS")
    (app / "Contents" / "Resources").mkdir(parents=True)
    # The build side is tested with a source of its own, so these tests do
    # not depend on the launcher being finished. What the real one says is
    # held below.
    mod.REAL_LAUNCHER_SRC = mod.LAUNCHER_SRC
    fake = tmp_path / "launcher.m"
    fake.write_text("// not compiled here\n", encoding="utf-8")
    monkeypatch.setattr(mod, "LAUNCHER_SRC", fake)
    return mod


def _record_commands(bm, monkeypatch):
    commands = []

    def fake_run(cmd, *a, **k):
        commands.append([str(c) for c in cmd])

        class Done:
            returncode, stdout, stderr = 0, "", ""
        return Done()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    return commands


def _write_bundle(bm, monkeypatch, arch="arm64"):
    monkeypatch.setattr(bm, "ARCH", arch)
    monkeypatch.setattr(bm, "write_icon", lambda: None)
    commands = _record_commands(bm, monkeypatch)
    bm.write_bundle()
    return commands


def test_the_build_compiles_the_launcher_source_with_cocoa_webkit_and_arc(bm, monkeypatch):
    commands = _write_bundle(bm, monkeypatch, "x86_64")
    clang = [c for c in commands if c and c[0] == "clang"]
    assert len(clang) == 1, commands
    cmd = clang[0]
    assert "-fobjc-arc" in cmd
    assert cmd[cmd.index("-arch") + 1] == "x86_64", "the architecture being built"
    assert "-mmacosx-version-min=" + bm.MACOS_MIN in cmd
    frameworks = [cmd[i + 1] for i, c in enumerate(cmd) if c == "-framework"]
    assert sorted(frameworks) == ["Cocoa", "WebKit"]
    assert cmd[cmd.index("-o") + 1] == str(bm.MACOS / "PaperPull")
    assert cmd[-1] == str(bm.LAUNCHER_SRC)
    assert bm.REAL_LAUNCHER_SRC == LAUNCHER, "and it is this file that is compiled for real"


def test_no_generated_c_stub_and_no_terminal_in_the_executable(bm, monkeypatch):
    source = (REPO / "packaging" / "build_macos.py").read_text(encoding="utf-8")
    assert "launcher.c" not in source and '"open", "-a"' not in source
    assert "-a Terminal" not in source
    commands = _write_bundle(bm, monkeypatch)
    assert not any(str(c).endswith(".c") for cmd in commands for c in cmd)
    assert not (bm.DIST / "cache" / "launcher.c").exists()


def test_a_missing_launcher_source_stops_the_build_and_says_so(bm, monkeypatch):
    monkeypatch.setattr(bm, "LAUNCHER_SRC", bm.DIST / "nowhere" / "launcher.m")
    commands = _record_commands(bm, monkeypatch)
    with pytest.raises(SystemExit) as stop:
        bm.compile_launcher()
    assert "launcher.m" in str(stop.value)
    assert commands == [], "clang is not run on a file that is not there"


def test_the_plist_lets_the_web_view_reach_the_panel_on_this_computer(bm, monkeypatch):
    _write_bundle(bm, monkeypatch)
    with open(bm.CONTENTS / "Info.plist", "rb") as f:
        plist = plistlib.load(f)
    assert plist["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True}, \
        "without it WKWebView refuses http://127.0.0.1"
    assert plist["NSPrincipalClass"] == "NSApplication"
    assert plist["LSApplicationCategoryType"] == "public.app-category.productivity"
    assert plist["CFBundleExecutable"] == "PaperPull"
    assert plist["LSMinimumSystemVersion"] == bm.MACOS_MIN
    assert "NSAllowsArbitraryLoads" not in plist["NSAppTransportSecurity"], \
        "only local networking is opened, never the web"


def test_the_terminal_script_and_the_command_line_shim_still_ship(bm, monkeypatch):
    _write_bundle(bm, monkeypatch)
    panel = (bm.RES / "paperpull-panel.sh").read_text(encoding="utf-8")
    assert '--host 127.0.0.1 --port "$PORT" --app-dir "$DIR/gui"' in panel
    assert 'PORT="${PAPERPULL_PORT:-8765}"' in panel, "8765 unless a test says otherwise"
    assert (bm.RES / "paperpull").is_file()
    if sys.platform != "win32":
        # Windows has no execute bit, so os.chmod(0o755) leaves both at 0o666
        # there. The bundle is only ever built and run on a Mac.
        assert (bm.RES / "paperpull-panel.sh").stat().st_mode & 0o111
        assert (bm.RES / "paperpull").stat().st_mode & 0o111


# -- the terminal script, run for real against a stand-in Python ---------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def panel_env(bm, monkeypatch, tmp_path):
    """The script as write_bundle() writes it, in a bundle whose python/bin/python3
    is a stand-in that listens on the port it is given (as uvicorn would) and
    notes that it started, and an `open` on PATH that records what it was
    asked to open."""
    if sys.platform == "win32":
        pytest.skip("a bash script")
    _write_bundle(bm, monkeypatch)
    res = tmp_path / "res"
    (res / "python" / "bin").mkdir(parents=True)
    (res / "gui").mkdir()
    script = res / "paperpull-panel.sh"
    script.write_text((bm.RES / "paperpull-panel.sh").read_text(encoding="utf-8"),
                      encoding="utf-8")
    script.chmod(0o755)
    py = res / "python" / "bin" / "python3"
    py.write_text(
        "#!%s\n"
        "import os, signal, socket, sys, time\n"
        "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "open(os.environ['STARTED'], 'w').write(str(os.getpid()))\n"
        "signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n"
        "s = socket.socket()\n"
        "s.bind(('127.0.0.1', port))\n"
        "s.listen()\n"
        "while True:\n"
        "    time.sleep(0.05)\n" % sys.executable, encoding="utf-8")
    py.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    opener = tools / "open"
    opener.write_text('#!/bin/sh\necho "$@" >> "$OPENED"\n', encoding="utf-8")
    opener.chmod(0o755)
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               STARTED=str(tmp_path / "started"), OPENED=str(tmp_path / "opened"),
               HOME=str(tmp_path), PAPERPULL_PORT=str(_free_port()))
    return script, env, tmp_path


def _start(script, env):
    """The script as a person's terminal starts it. SIGINT is put back to its
    default first: a test runner started from a script or a background job
    has it ignored, and a shell cannot trap a signal it inherited ignored."""
    return subprocess.Popen(
        ["/bin/bash", str(script)], env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))


def _wait_for(path, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return True
        time.sleep(0.05)
    return False


def test_the_terminal_script_opens_the_browser_once_the_panel_answers(panel_env):
    script, env, tmp = panel_env
    proc = _start(script, env)
    try:
        assert _wait_for(tmp / "opened"), "the browser was never opened"
        assert (tmp / "opened").read_text(encoding="utf-8").split() == \
            ["http://127.0.0.1:" + env["PAPERPULL_PORT"]]
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=20)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_stopping_the_terminal_script_stops_the_panel_it_started(panel_env, sig):
    script, env, tmp = panel_env
    proc = _start(script, env)
    assert _wait_for(tmp / "opened"), "the panel never came up"
    pid = int((tmp / "started").read_text(encoding="utf-8"))
    proc.send_signal(sig)
    proc.communicate(timeout=20)
    end = time.time() + 10
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    os.kill(pid, signal.SIGKILL)
    pytest.fail("the panel outlived the script that started it")


def test_a_taken_port_means_no_panel_no_browser_and_a_message_to_quit_the_app(panel_env):
    script, env, tmp = panel_env
    with socket.socket() as held:
        held.bind(("127.0.0.1", int(env["PAPERPULL_PORT"])))
        held.listen()
        done = REAL_RUN(["/bin/bash", str(script)], env=env, capture_output=True,
                              text=True, timeout=30)
    assert done.returncode != 0
    assert "PaperPull.app" in done.stderr and "quit" in done.stderr.lower()
    assert not (tmp / "started").exists(), "a second panel was started on a taken port"
    assert not (tmp / "opened").exists(), "the browser was sent to somebody else's panel"


def test_a_panel_that_dies_before_it_answers_is_not_opened_in_the_browser(panel_env):
    script, env, tmp = panel_env
    (script.parent / "python" / "bin" / "python3").write_text(
        "#!/bin/sh\necho failed to bind >&2\nexit 3\n", encoding="utf-8")
    done = REAL_RUN(["/bin/bash", str(script)], env=env, capture_output=True,
                          text=True, timeout=30)
    assert done.returncode == 3
    assert "PaperPull.app" in done.stderr
    assert not (tmp / "opened").exists()


def test_the_readme_first_describes_a_window_not_a_terminal(bm, monkeypatch):
    _write_bundle(bm, monkeypatch)
    text = (bm.RES / "README-FIRST.txt").read_text(encoding="utf-8")
    assert "Cmd-Q" in text
    assert "~/Library/Logs/PaperPull/panel.log" in text
    assert "Contents/Resources/paperpull <app> <command>" in text
    assert "Terminal window" not in text and "browser tab" not in text
    assert "Nothing is sent anywhere" in text


def test_the_audit_refuses_a_main_executable_that_is_not_a_mach_o(bm, monkeypatch):
    bm.MACOS.mkdir(parents=True)
    (bm.MACOS / "PaperPull").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        bm.audit()
    assert "Mach-O" in str(stop.value)


def test_the_launcher_is_compiled_from_the_checkout_not_staged_from_git(bm, monkeypatch):
    """The launcher source is read where it lies, so a source that is new and
    not yet committed builds, and it is not copied into the bundle, because
    packaging is not one of the folders stage_code() carries."""
    assert not bm.wanted("packaging/macos/launcher.m")
    monkeypatch.setattr(bm, "tracked_files",
                        lambda: ["packaging/macos/launcher.m", "packaging/build_macos.py"])
    assert bm.stage_code() == 0
    assert not list(bm.RES.rglob("launcher.m"))
    assert not (bm.RES / "packaging").exists()


def _signing_commands(bm, monkeypatch):
    """sign() run over a bundle of stand-in Mach-O files, with codesign recorded
    instead of run. Returns the codesign argument lists, in order."""
    macho = b"\xcf\xfa\xed\xfe" + b"\0" * 12
    (bm.MACOS).mkdir(parents=True)
    (bm.MACOS / "PaperPull").write_bytes(macho)
    py = bm.RES / "python" / "bin"
    py.mkdir(parents=True)
    (py / "python3.12").write_bytes(macho)
    lib = bm.RES / "python" / "lib" / "lib-dynload"
    lib.mkdir(parents=True)
    (lib / "_ssl.so").write_bytes(macho)
    (bm.RES / "paperpull").write_text("#!/bin/sh\n", encoding="utf-8")
    (bm.DIST / "cache").mkdir(parents=True)
    return _record_commands(bm, monkeypatch)


def _entitlements_of(cmd):
    if "--entitlements" not in cmd:
        return None
    with open(cmd[cmd.index("--entitlements") + 1], "rb") as f:
        return plistlib.load(f)


def test_the_launcher_is_signed_with_the_hardened_runtime_and_no_entitlements(bm, monkeypatch):
    commands = _signing_commands(bm, monkeypatch)
    launcher = str(bm.MACOS / "PaperPull")
    seen_entitlements = {}
    real_run = bm.subprocess.run

    def run(cmd, *a, **k):
        # The entitlements file is only there while sign() runs, so read it now.
        if "--entitlements" in cmd:
            seen_entitlements[tuple(cmd)] = _entitlements_of(cmd)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(bm.subprocess, "run", run)
    bm.sign("Developer ID Application: Test (ABCDE12345)")
    signs = [c for c in commands if c[:2] == ["codesign", "--force"]]
    assert signs, commands

    def options(cmd):
        return cmd[cmd.index("--options") + 1]

    for cmd in signs:
        assert options(cmd) == "runtime", "every signature has the hardened runtime"
        assert "--deep" not in cmd

    on_launcher = [c for c in signs if launcher in c]
    assert len(on_launcher) == 1, "signed on its own, once"
    assert "--entitlements" not in on_launcher[0], "the launcher gets none"
    assert on_launcher[0][-1] == launcher

    bundle = [c for c in signs if c[-1] == str(bm.APP)]
    assert len(bundle) == 1 and signs[-1] is bundle[0], "the bundle is sealed last"
    assert "--entitlements" not in bundle[0], \
        "codesign applies a bundle-level --entitlements to the main executable"
    assert signs.index(on_launcher[0]) < signs.index(bundle[0])

    python = [c for c in signs if str(bm.RES / "python" / "bin" / "python3.12") in c]
    assert len(python) == 1
    assert seen_entitlements[tuple(python[0])] == bm.ENTITLEMENTS
    assert set(bm.ENTITLEMENTS) == {
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "com.apple.security.cs.disable-library-validation"}
    assert str(bm.RES / "python" / "lib" / "lib-dynload" / "_ssl.so") in python[0], \
        "extension modules are signed with the interpreter's entitlements too"
    # Nothing but the python tree is signed with entitlements.
    with_ent = [c for c in signs if "--entitlements" in c]
    assert all(launcher not in c and str(bm.APP) not in c for c in with_ent)
    assert commands[-1][:2] == ["codesign", "--verify"]


# -- the source's side of the contract ----------------------------------------

@pytest.fixture()
def source():
    assert LAUNCHER.is_file(), "packaging/macos/launcher.m is what build_macos.py compiles"
    return LAUNCHER.read_text(encoding="utf-8")


def test_the_launcher_source_reads_the_two_environment_variables(source):
    assert "PAPERPULL_LAUNCHER_SELFTEST" in source
    assert "PAPERPULL_PORT" in source
    for mode in ('"ready"', '"window"'):
        assert mode in source, mode


def test_the_launcher_source_speaks_the_lines_the_workflow_reads(source):
    assert "READY http://127.0.0.1:" in source
    assert "WINDOW title=" in source


def test_the_launcher_source_uses_the_frameworks_it_is_linked_with(source):
    assert re.search(r"#import <Cocoa/Cocoa\.h>|#import <AppKit/AppKit\.h>", source)
    assert re.search(r"#import <WebKit/WebKit\.h>", source)
    assert "WKWebView" in source


def test_the_launcher_source_runs_the_panel_the_way_the_terminal_script_does(source):
    for needed in ("python/bin/python3", "uvicorn", "app:app", "--app-dir", "127.0.0.1",
                   "PYTHONNOUSERSITE", "PYTHONPYCACHEPREFIX", "panel.log"):
        assert needed in source, needed
    assert "8765" in source
    assert "http://localhost" not in source and "http://[::1]" not in source, \
        "the panel's Host check allows them, but the web view must use 127.0.0.1"


# -- the workflow --------------------------------------------------------------

def _steps():
    """The workflow's steps as {name: lines}, comments left out. PyYAML is not
    a dependency of the tests, so the file is split on its own step markers."""
    steps, name = {}, None
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^      - (?:name|uses): (.*)$", line)
        if m:
            name = m.group(1).strip()
            steps[name] = []
        if name and not line.lstrip().startswith("#"):
            steps[name].append(line)
    return {k: "\n".join(v) for k, v in steps.items()}


def _order():
    text = WORKFLOW.read_text(encoding="utf-8")
    return [m.group(1).strip() for m in re.finditer(r"^      - name: (.*)$", text, re.M)]


READY = "Prove the app's own executable starts the panel"
WINDOW = "Prove the app's own executable opens its window (may fail on a headless runner)"


def test_the_workflow_runs_the_apps_own_executable_in_ready_mode_after_the_panel_proof():
    steps, order = _steps(), _order()
    first = "Prove the panel starts from the bundle"
    gate = "What Gatekeeper will say"
    assert order.index(first) < order.index(READY) < order.index(gate), \
        "the existing step stays, the new one follows it"
    assert order.index("Build, sign, notarize and staple") < order.index(READY), \
        "it is the signed executable that runs"
    step = steps[READY]
    assert "PAPERPULL_LAUNCHER_SELFTEST=ready" in step
    assert "dist/PaperPull.app/Contents/MacOS/PaperPull" in step
    assert "grep -Eq '^READY http://127\\.0\\.0\\.1:[0-9]+$' ready.out" in step
    assert "sleep 90" in step, "a launcher that hangs does not hold the job"
    assert "test \"$status\" = 0" in step
    assert re.search(r"^\s+if:", step, re.M) is None, \
        "it runs for both architectures, signed or not"
    assert "continue-on-error" not in step, "the ready step is the hard gate"


def test_the_workflow_also_tries_the_window_and_may_fail_there():
    steps, order = _steps(), _order()
    assert order.index(READY) < order.index(WINDOW) < order.index("What Gatekeeper will say"), \
        "after the build and signing, beside the ready step"
    assert order.index("Build, sign, notarize and staple") < order.index(WINDOW)
    step = steps[WINDOW]
    assert re.search(r"^\s+continue-on-error: true$", step, re.M), \
        "a headless runner has no display, so this one may fail without failing the job"
    assert "PAPERPULL_LAUNCHER_SELFTEST=window" in step
    assert "dist/PaperPull.app/Contents/MacOS/PaperPull" in step
    assert "sleep 90" in step
    assert "lipo -archs" in step
    assert "test \"$status\" = 0" in step
    assert "grep -Eq '^WINDOW title=PaperPull$' window.out" in step
    assert re.search(r"^\s+if:", step, re.M) is None
    text = WORKFLOW.read_text(encoding="utf-8")
    comment = text[:text.index("- name: " + WINDOW)].rsplit("\n\n", 1)[-1]
    comment = " ".join(comment.replace("#", " ").split())
    assert "allowed to fail" in comment and "display" in comment, \
        "and the comment says plainly why"
