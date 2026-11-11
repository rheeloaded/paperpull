"""No request this repository's own code sends to this computer goes
through a proxy.

urllib's urlopen, and any opener built without ProxyHandler({}), send a
request through the proxy the computer names, HTTP_PROXY in the
environment or, when that is empty, the proxy in the system settings of
Windows or macOS. Nothing there exempts 127.0.0.1 unless the person listed
it, and the Windows box for local addresses covers only names without a
dot. A proxy cannot reach a browser's debugging port, the panel or a test's
own fake site, so with one set the sign-in step said no debugging port
answered, for a browser that was fine (shown on Windows and in WSL on
2026-10-06). A census that day found 35 such requests, in the core, the
testkit, ten browser test files, the panel's server tests and the server's
self-test and smoke run. Run again on 2026-10-27 it found seven more made
since, two of them in the sign-in itself (debug_port_holder and
_open_tab_in, which ask whether a browser already holds the port and open
the sign-in page there), the rest in PayPal's browser test, two of the
panel's tests and the self-test's network check. Each now goes through
browser.open_local or an opener built with ProxyHandler({}).

A request is found by what it does. Every tracked Python file is read and
its imports are followed to what they bind, under any name, so urlopen is
found however it is reached, and an opener is judged where it is built.
http.client and sockets never read a proxy setting and are left alone.
Another HTTP client would read one, so its import has to be named here
too. Names are followed within one file only, so urlopen handed on by
another module of this repository would not be seen, and none is. The one
request meant for the internet, where a proxy the person set should carry
it, is named below with its reason.

It needs no browser.
"""
import ast
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Requests meant for the internet, by file and function, which a proxy the
# person set should carry.
FOR_THE_INTERNET = {
    ("packaging/build_windows.py", "fetch"): "downloads Python and get-pip.py for the Windows build",
    ("gui/updater.py", "_open"): "the opt-in update check and its download, both from github.com",
}

# Each reads the proxy settings for every request it sends.
READS_PROXIES = {"urllib.request.urlopen", "urllib.request.urlretrieve",
                 "urllib.request.URLopener", "urllib.request.FancyURLopener"}
OPENERS = {"urllib.request.build_opener"}
PROXY_HANDLER = "urllib.request.ProxyHandler"
# websockets' client among them, since its 15.0.
OTHER_CLIENTS = {"requests", "httpx", "urllib3", "aiohttp", "pycurl", "websockets"}

HOW = ("Send a request to this computer through paperpull_core.browser.open_local, or build "
       "its opener with urllib.request.ProxyHandler({}). A request meant for the internet "
       "is named in FOR_THE_INTERNET with its reason.")


class Requests(ast.NodeVisitor):
    """Every way one file sends a request that reads the proxy settings, as
    (line, function, what)."""

    def __init__(self, package=None):
        self.package = package
        self.names = {}
        self.inside = []
        self.found = []

    def _report(self, node, what):
        self.found.append((node.lineno, ".".join(self.inside) or "<module>", what))

    # -- what each name is ---------------------------------------------------

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                self.names[alias.asname] = alias.name
            else:
                top = alias.name.split(".")[0]
                self.names[top] = top
            if alias.name.split(".")[0] in OTHER_CLIENTS:
                self._report(node, "imports %s, an HTTP client that reads the proxy settings"
                             % alias.name)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        if node.level:
            if not self.package:
                return
            parts = self.package.split(".")
            parts = parts[:len(parts) - node.level + 1]
            module = ".".join(parts + ([node.module] if node.module else []))
        if module.split(".")[0] in OTHER_CLIENTS:
            self._report(node, "imports %s, an HTTP client that reads the proxy settings" % module)
        for alias in node.names:
            if alias.name == "*":
                if module in ("urllib.request", "urllib"):
                    self._report(node, "takes every name of %s, which this check cannot follow"
                                 % module)
                continue
            self.names[alias.asname or alias.name] = module + "." + alias.name

    def resolve(self, node):
        """The dotted name an expression stands for, or None."""
        tail = []
        while isinstance(node, ast.Attribute):
            tail.append(node.attr)
            node = node.value
        base = None
        if isinstance(node, ast.Name):
            base = self.names.get(node.id) or (node.id if node.id in ("__import__", "getattr")
                                               else None)
        elif isinstance(node, ast.Call) and node.args and self.resolve(node.func) == "__import__":
            # The top package, or the module itself once a fromlist names
            # something in it.
            name = node.args[0]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                fromlist = node.args[3:4] + [k.value for k in node.keywords if k.arg == "fromlist"]
                named = any(not (isinstance(f, ast.Constant) and not f.value)
                            and not (isinstance(f, (ast.List, ast.Tuple)) and not f.elts)
                            for f in fromlist)
                base = name.value if named else name.value.split(".")[0]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[-1], ast.Constant):
            called = self.resolve(node.func)
            given = node.args[-1].value
            if called == "importlib.import_module" and isinstance(given, str):
                base = given
            elif called == "getattr" and len(node.args) == 2 and isinstance(given, str):
                owner = self.resolve(node.args[0])
                base = owner and owner + "." + given
        if base is None:
            return None
        return ".".join([base] + tail[::-1])

    def visit_Assign(self, node):
        # A name given to urlopen, or to functools.partial(urlopen, ...), is
        # urlopen from then on, and one given a module imported by its name
        # (importlib.import_module("urllib.request")) is that module.
        value = node.value
        if isinstance(value, ast.Call) and self.resolve(value.func) == "functools.partial" \
                and value.args:
            value = value.args[0]
        target = self.resolve(value) if isinstance(value, (ast.Name, ast.Attribute, ast.Call)) \
            else None
        if target:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.names[t.id] = target
        self.generic_visit(node)

    # -- where the requests are ----------------------------------------------

    def visit_FunctionDef(self, node):
        self.inside.append(node.name)
        self.generic_visit(node)
        self.inside.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _no_proxies(self, node):
        if not (isinstance(node, ast.Call) and self.resolve(node.func) == PROXY_HANDLER):
            return False
        given = list(node.args) + [k.value for k in node.keywords if k.arg == "proxies"]
        return len(given) == 1 and isinstance(given[0], ast.Dict) and not given[0].keys

    def visit_Call(self, node):
        called = self.resolve(node.func)
        if called in OPENERS and not any(self._no_proxies(a) for a in node.args):
            self._report(node, "builds an opener without ProxyHandler({})")
        elif called == PROXY_HANDLER and not self._no_proxies(node):
            self._report(node, "builds a ProxyHandler that reads or names a proxy")
        elif self.resolve(node) in READS_PROXIES:      # getattr(urllib.request, "urlopen")
            self._report(node, "uses %s" % self.resolve(node))
        self.generic_visit(node)

    def _reference(self, node):
        if isinstance(node.ctx, ast.Load) and self.resolve(node) in READS_PROXIES:
            self._report(node, "uses %s" % self.resolve(node))

    def visit_Attribute(self, node):
        # Every link of a chain is checked once here, and then only what the
        # chain starts from is read further.
        while isinstance(node, ast.Attribute):
            self._reference(node)
            node = node.value
        self.visit(node)

    def visit_Name(self, node):
        self._reference(node)


def requests_in(source, rel=""):
    parts = Path(rel).parts
    package = None
    if "paperpull_core" in parts:
        package = ".".join(parts[parts.index("paperpull_core"):-1])
    found = Requests(package)
    found.visit(ast.parse(source))
    return found.found


def tracked_python():
    git = shutil.which("git")
    if not git:
        pytest.skip("git is not installed")
    listed = subprocess.run([git, "ls-files", "-z", "--", "*.py"], cwd=REPO, capture_output=True)
    if listed.returncode:
        pytest.skip("not a git checkout")
    return [rel for rel in listed.stdout.decode("utf-8").split("\0") if rel]


def test_no_request_to_this_computer_goes_through_a_proxy():
    wrong, named = [], set()
    for rel in tracked_python():
        source = (REPO / rel).read_text(encoding="utf-8")
        for line, function, what in requests_in(source, rel):
            if (rel, function) in FOR_THE_INTERNET:
                named.add((rel, function))
                continue
            wrong.append("%s:%d in %s %s" % (rel, line, function, what))
    assert not wrong, "These requests read the proxy settings. %s\n%s" % (HOW, "\n".join(wrong))
    assert named == set(FOR_THE_INTERNET), \
        "Named for the internet but no longer sending anything: %s" % sorted(set(FOR_THE_INTERNET) - named)


# Each way of reaching urlopen or a proxy-reading opener that the check has
# to see, and the ways that read no proxy setting.
SAMPLES = [
    ("import urllib.request\nurllib.request.urlopen(u)", True),
    ("import urllib.request as ur\nur.urlopen(u)", True),
    ("from urllib.request import urlopen as fetch\nfetch(u)", True),
    ("from urllib import request\nrequest.urlopen(u, timeout=2)", True),
    ("import importlib\nimportlib.import_module('urllib.request').urlopen(u)", True),
    ("__import__('urllib.request').request.urlopen(u)", True),
    ("__import__('urllib.request', fromlist=['urlopen']).urlopen(u)", True),
    ("__import__('urllib.request', None, None, ['urlopen']).urlopen(u)", True),
    ("import importlib\nm = importlib.import_module('urllib.request')\nm.urlopen(u)", True),
    ("m = __import__('urllib.request', fromlist=['urlopen'])\nm.urlopen(u)", True),
    ("from websockets.sync.client import connect\nconnect(u)", True),
    ("import urllib.request\ngetattr(urllib.request, 'urlopen')(u)", True),
    ("import urllib.request\nask = urllib.request.urlopen\n", True),
    ("import functools, urllib.request\nask = functools.partial(urllib.request.urlopen, timeout=2)\n"
     "ask(u)", True),
    ("import urllib.request\nretry(urllib.request.urlretrieve, u)", True),
    ("import urllib.request\nurllib.request.urlopen.__call__(u)", True),
    ("import urllib.request\nwrap(urllib.request.urlopen).answer.text", True),
    ("from urllib.request import *\nurlopen(u)", True),
    ("import urllib.request\nurllib.request.build_opener().open(u)", True),
    ("import urllib.request\nclass Stay(urllib.request.HTTPRedirectHandler):\n    pass\n"
     "OPENER = urllib.request.build_opener(Stay)\n", True),
    ("import urllib.request\nurllib.request.build_opener(urllib.request.ProxyHandler()).open(u)", True),
    ("import urllib.request\nurllib.request.ProxyHandler({'http': 'http://p:1'})", True),
    ("import requests\nrequests.get(u)", True),
    ("from httpx import Client\nClient().get(u)", True),
    ("import urllib.request\nurllib.request.build_opener(urllib.request.ProxyHandler({})).open(u)", False),
    ("from urllib.request import ProxyHandler, build_opener\n"
     "build_opener(Stay, ProxyHandler(proxies={})).open(u)", False),
    ("from paperpull_core import browser as browser_launcher\n"
     "browser_launcher.open_local(u, timeout=2)", False),
    ("import urllib.request\nreq = urllib.request.Request(u, method='PUT')", False),
    ("import http.client\nhttp.client.HTTPConnection('127.0.0.1', 1).request('GET', '/')", False),
    ("import socket\nsocket.create_connection(('127.0.0.1', 1))", False),
    ("def urlopen(u):\n    return u\nurlopen(u)", False),
    ("import importlib\nm = importlib.import_module('json')\nm.loads(u)", False),
    ("m = __import__('urllib.request', fromlist=[])\nm.request.Request(u)", False),
]


@pytest.mark.parametrize("source,reads", SAMPLES, ids=range(len(SAMPLES)))
def test_the_check_sees_each_way_a_request_is_sent(source, reads):
    found = requests_in(source)
    assert bool(found) is reads, found


def test_a_relative_import_inside_the_core_is_followed():
    """testkit reaches open_local as from .browser import open_local, and
    the same import of urlopen would have to count."""
    rel = "core/paperpull_core/testkit.py"
    assert requests_in("from .browser import open_local\nopen_local(u, timeout=2)", rel) == []
    assert requests_in("from urllib.request import urlopen\nurlopen(u)", rel)
