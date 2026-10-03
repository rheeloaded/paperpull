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
    container is never given."""
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


def test_compose_uses_it_and_never_switches_the_filter_off():
    text = (SERVER / "compose.yaml").read_text(encoding="utf-8")
    assert "seccomp=./seccomp-chrome.json" in text
    assert "unconfined" not in text
    assert "SYS_ADMIN" not in text and "privileged" not in text
