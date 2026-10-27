"""The container's security profile is Docker's, with only what Chrome needs.

Chrome shuts every page inside a user namespace of its own, and Docker's
default profile lets a container make one only with CAP_SYS_ADMIN, which
would also let it mount filesystems. seccomp-chrome.json allows `clone`
with namespace flags and `unshare` to every process and leaves everything
else as Docker ships it. These tests hold the file to that, and to the
unmodified profile it came from.
"""
import hashlib
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

import seccomp  # noqa: E402

DEFAULT = json.loads((SERVER / "seccomp" / "moby-default.json").read_text(encoding="utf-8"))
CHROME = json.loads((SERVER / "seccomp-chrome.json").read_text(encoding="utf-8"))


def allow_rules(profile, name):
    return [r for r in profile["syscalls"]
            if name in r.get("names", []) and r["action"] == "SCMP_ACT_ALLOW"]


def unconditional(rule) -> bool:
    return not rule.get("args") and not rule.get("includes") and not rule.get("excludes")


def test_the_profile_is_what_the_generator_makes():
    assert (SERVER / "seccomp-chrome.json").read_text(encoding="utf-8") == seccomp.expected()


def test_the_docker_profile_is_the_one_the_readme_names():
    """Released moby/profiles seccomp/v0.2.4, unmodified."""
    digest = hashlib.sha256((SERVER / "seccomp" / "moby-default.json").read_bytes()).hexdigest()
    readme = (SERVER / "seccomp" / "README.md").read_text(encoding="utf-8")
    assert digest in readme, digest


def test_its_license_travels_with_it():
    text = (SERVER / "seccomp" / "LICENSE-APACHE-2.0").read_text(encoding="utf-8")
    assert "Apache License" in text and "Version 2.0" in text
    assert "server/seccomp" in (SERVER.parent / "NOTICE.md").read_text(encoding="utf-8")


def test_anything_not_allowed_is_still_refused():
    assert CHROME["defaultAction"] == "SCMP_ACT_ERRNO"
    assert CHROME["defaultErrnoRet"] == DEFAULT["defaultErrnoRet"]


def test_chrome_can_make_its_namespaces():
    for name in ("clone", "unshare"):
        rules = allow_rules(CHROME, name)
        assert rules and all(unconditional(r) for r in rules), (name, rules)


def test_nothing_else_docker_keeps_for_an_admin_is_let_out():
    """mount, setns, bpf and the rest still need CAP_SYS_ADMIN, which the
    container is not given unless the Synology opt-in adds it."""
    admin = [r for r in DEFAULT["syscalls"]
             if r.get("includes", {}).get("caps") == ["CAP_SYS_ADMIN"]
             and r["action"] == "SCMP_ACT_ALLOW"]
    gated = {n for r in admin for n in r["names"]} - {"clone", "unshare"}
    assert {"mount", "setns", "bpf", "umount2"} <= gated
    for name in gated:
        rules = allow_rules(CHROME, name)
        # Each still needs a capability (syslog, for one, also to CAP_SYSLOG
        # holders, as Docker has it), and its rules are Docker's own.
        assert rules and all(r.get("includes", {}).get("caps") for r in rules), (name, rules)
        assert [strip(r) for r in rules] == [strip(r) for r in allow_rules(DEFAULT, name)], name


def strip(rule):
    """A rule without the two calls this profile takes out of it."""
    return dict(rule, names=[n for n in rule["names"] if n not in ("clone", "unshare")])


def test_every_other_rule_is_dockers_own():
    """Take away the two calls from both profiles, and what is left is the
    same list of rules."""
    def without(profile):
        rules = []
        for rule in profile["syscalls"]:
            names = [n for n in rule.get("names", []) if n not in ("clone", "unshare")]
            if names:
                rules.append(json.dumps(dict(rule, names=names), sort_keys=True))
        return rules

    assert without(CHROME) == without(DEFAULT)
    assert {k: v for k, v in CHROME.items() if k != "syscalls"} == \
        {k: v for k, v in DEFAULT.items() if k != "syscalls"}


def active(text: str) -> str:
    """The lines a compose file acts on, its comments left out."""
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


def test_compose_uses_it_and_never_switches_the_filter_off():
    text = (SERVER / "compose.yaml").read_text(encoding="utf-8")
    assert "seccomp=./seccomp-chrome.json" in text
    assert "unconfined" not in text
    # The Synology setuid-sandbox fallback is offered as a commented-out
    # opt-in (SYS_ADMIN in cap_add, see the test below), so that word
    # appears in a comment. Nothing the file acts on by default weakens the
    # sandbox.
    on = active(text)
    assert "SYS_ADMIN" not in on and "privileged" not in on


def test_the_synology_fallback_is_offered_but_off_by_default():
    """A NAS kernel without user namespaces (some Synology) cannot run the
    namespace sandbox, so both compose files offer Chrome's setuid sandbox to
    turn on, commented out until then. It keeps the sandbox on, adding a
    capability rather than taking the filter away, and removing the # leaves
    valid YAML, the trap the graphics block met once. It also needs
    no-new-privileges off, which a # in front of its line does, leaving
    valid YAML too."""
    for name in ("compose.yaml", "compose.https.yaml"):
        lines = (SERVER / name).read_text(encoding="utf-8").splitlines()
        assert lines.count("      #- SYS_ADMIN") == 1, name
        assert "      #- SYS_ADMIN".replace("#", "", 1) == "      - SYS_ADMIN"
        at = lines.index("      #- SYS_ADMIN")
        # In the paperpull service's cap_add, under the seven it keeps, with
        # only its own comment between.
        kept = lines.index("    cap_add:")
        assert lines[kept + 1:kept + 8] == [
            "      - %s" % cap for cap in ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID",
                                          "KILL", "SYS_CHROOT")], name
        assert all(line.startswith("      # ") for line in lines[kept + 8:at]), name
        nnp = lines.index("      - no-new-privileges:true")
        assert lines[nnp - 2:nnp] == ["    security_opt:", "      - seccomp=./seccomp-chrome.json"]
        assert nnp < at


def test_the_setuid_helper_follows_the_capability():
    """chrome.sh makes Chrome's sandbox helper setuid root only in a
    container holding CAP_SYS_ADMIN, bit 21 of CapBnd, the one sign of the
    opt-in, and takes the bit off every other copy. It never gives the
    helper to root, and sets the bit only where root alone could have put
    it, see test_the_setuid_helper_needs_a_path_root_owns.py.
    server/smoke.py checks the same in a running container."""
    script = (SERVER / "chrome.sh").read_text(encoding="utf-8")
    assert "/^CapBnd:/" in script and ">> 21) & 1" in script
    # Only beside the seccomp-bpf filter, asked of the server's one host
    # check, so Chrome never gets half its sandbox through the helper.
    gate = script.index("check().seccomp_bpf == 'yes'")
    assert gate < script.index("if ! kernel_has_seccomp; then") < script.index("SETUID_SANDBOX=1")
    helpers = script[script.index("sandbox_helpers() {"):]
    assert helpers.index('chmod u-s,g-s "$helper"') < helpers.index('may_be_setuid "$1"')
    assert helpers.index('may_be_setuid "$1"') < helpers.index("chmod 4755")
    assert '[ ! -L "$helper" ]' in helpers and "chown" not in helpers
    # Set after the recursive chmod, in the function every start path calls.
    readable = script[script.index("readable() {"):script.index("sandbox_helpers() {")]
    assert readable.index('chmod -R a+rX') < readable.index('sandbox_helpers "$1"')
