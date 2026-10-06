"""No request from Playwright's own client follows a redirect it did not check.

page.request and page.context.request ask from outside the page, with every
cookie the attached browser holds for the host they ask, and the attached
browser is the person's own profile, so that can be any site they use. Left
to itself the client follows twenty redirects and checks none of them. A
review of the AAFMAA capture fix (2026-10-05) had a made-up provider at
localhost answer a document's address with a 302 to 127.0.0.1, and
capture.fetch_pdf sent a GET there with the cookies the browser held for it
and kept the PDF that came back. Every app checked the address it was
handed. Most never checked where a redirect led, and the four that did
checked only where the redirects ended, after every step had been asked.
Measured in Chromium 153
attached over CDP, with Playwright 1.62 and 1.63 alike, max_redirects=0
hands back the redirect itself and asks nothing more.

So every call into that client passes max_redirects=0, written as the
number itself, and asks one address. A provider's link that may be sent on
goes through paperpull_core.redirects.get, which asks each hop that way and
checks the Location with the app's own guard before asking it, and that
module is the only code that reads where a redirect points.

The calls are found by what they do, never by what anything is called. A
client is the `request` of anything (page.request, page.context.request,
ctx.request), what request.new_context() makes, a name or a self attribute
one is kept in, a parameter one is handed to wherever the call that hands it
over can be found in apps/ or core/, and what a function that returns one
returns. A Route a handler is given is one too, since its fetch asks through
the same client. A call is any of the seven methods that send something. A
method taken off a client without being called is named as well, since a
call through it could not be checked. The Request a response carries is
someone's `request` too, but nothing that sends is ever called on one, so it
never turns up as a call.

test_a_redirect_off_the_allowlist_is_never_asked.py shows the helper and
each changed app in a real browser.
"""
import ast
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What sends a request through Playwright's client. APIRequestContext has all
# seven, and Route.fetch asks through the same client.
SENDS = ("get", "post", "put", "patch", "delete", "head", "fetch")
# The one module that may read where a redirect points.
WALKER = "core/paperpull_core/redirects.py"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
# What binds a name, hands a value on or hands one back.
FACTS = (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.With, ast.AsyncWith, ast.For,
         ast.AsyncFor, ast.Return, ast.Call)
# What reads one header of an answer by its name.
HEADER_READS = ("get", "header_value", "header_values", "pop", "setdefault")


class Source:
    """One module, read once."""

    def __init__(self, name: str, text: str):
        self.name = name
        self.tree = ast.parse(text)
        self.parent = {}
        # The function each node sits in, worked out once.
        self.scope = {}
        stack = [(self.tree, None)]
        while stack:
            node, scope = stack.pop()
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
                self.scope[child] = scope
                stack.append((child, child if isinstance(child, FUNCTIONS) else scope))
        # Only these can teach the census anything.
        self.facts = [n for n in ast.walk(self.tree) if isinstance(n, FACTS)]
        self.defs = defaultdict(list)
        for node in ast.walk(self.tree):
            if isinstance(node, DEFS):
                self.defs[node.name].append(node)
        self.modules = {}    # local name -> the module it stands for
        self.imported = {}   # local name -> (module, its name there)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.modules[a.asname] = a.name
                    else:
                        self.modules[a.name.split(".")[0]] = a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = "." * node.level + (node.module or "")
                for a in node.names:
                    self.imported[a.asname or a.name] = (base, a.name)

    def scope_of(self, node):
        """The function a node sits in, or None at module level."""
        return self.scope.get(node)

    def scopes(self, scope):
        """A scope and every scope around it, out to the module."""
        while scope is not None:
            yield scope
            scope = self.scope_of(scope)
        yield None


def _joined(base: str, name: str) -> str:
    return base + name if base.endswith(".") else base + "." + name


class Census:
    """Every request client in a set of modules, and every call into one."""

    def __init__(self, sources):
        self.sources = {s.name: s for s in sources}
        self.names = defaultdict(set)    # (module, scope) -> names holding a client
        self.routes = defaultdict(set)   # (module, scope) -> names holding a Route
        self.attrs = defaultdict(set)    # module -> self attributes holding a client
        self.returns = set()             # functions that hand back a client
        self.handed = []                 # (module, call, the function it reaches)
        self._settle()

    # -- where a name leads ----------------------------------------------------

    def module(self, source, dotted: str):
        """The module a dotted name means from inside `source`. The core's by
        its package or relatively, an app's own modules by their file name."""
        folder = source.name.rsplit("/", 1)[0]
        if dotted.startswith("."):
            rest = dotted.lstrip(".")
            return self.sources.get("%s/%s.py" % (folder, rest.replace(".", "/"))) if rest else None
        if dotted.startswith("paperpull_core."):
            return self.sources.get("core/paperpull_core/%s.py"
                                    % dotted.split(".", 1)[1].replace(".", "/"))
        if source.name.startswith("apps/") and "." not in dotted:
            return self.sources.get("%s/%s.py" % (folder, dotted))
        return None

    def module_called(self, source, local: str):
        """The module a local name stands for, when it stands for one."""
        if local in source.modules:
            return self.module(source, source.modules[local])
        if local in source.imported:
            return self.module(source, _joined(*source.imported[local]))
        return None

    def functions_called(self, source, func):
        """(module, function) for everything a called expression may be."""
        if isinstance(func, ast.Name):
            out = [(source, d) for d in source.defs.get(func.id, [])]
            if func.id in source.imported:
                base, name = source.imported[func.id]
                there = self.module(source, base)
                if there is not None:
                    out += [(there, d) for d in there.defs.get(name, [])]
            return out
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            owner = func.value.id
            if owner in ("self", "cls"):
                return [(source, d) for d in source.defs.get(func.attr, [])]
            there = self.module_called(source, owner)
            if there is not None:
                return [(there, d) for d in there.defs.get(func.attr, [])]
        return []

    # -- what holds a client -----------------------------------------------------

    def _named(self, table, source, name: str, scope) -> bool:
        return any(name in table[(source.name, s)] for s in source.scopes(scope))

    def is_client(self, source, expr, scope) -> bool:
        if isinstance(expr, ast.Attribute):
            if expr.attr == "request":
                return True
            if isinstance(expr.value, ast.Name) and expr.value.id in ("self", "cls"):
                return expr.attr in self.attrs[source.name]
            return False
        if isinstance(expr, ast.Name):
            return self._named(self.names, source, expr.id, scope)
        if isinstance(expr, ast.Call):
            f = expr.func
            if isinstance(f, ast.Attribute) and f.attr == "new_context" and \
                    isinstance(f.value, ast.Attribute) and f.value.attr == "request":
                return True
            if isinstance(f, ast.Name) and f.id == "getattr" and len(expr.args) >= 2 and \
                    isinstance(expr.args[1], ast.Constant) and expr.args[1].value == "request":
                return True
            return any(d in self.returns for _s, d in self.functions_called(source, f))
        if isinstance(expr, ast.IfExp):
            return self.is_client(source, expr.body, scope) or \
                self.is_client(source, expr.orelse, scope)
        if isinstance(expr, ast.BoolOp):
            return any(self.is_client(source, v, scope) for v in expr.values)
        if isinstance(expr, ast.NamedExpr):
            return self.is_client(source, expr.value, scope)
        return False

    def sends_through(self, source, expr, scope, method: str) -> bool:
        """Whether `expr.method(...)` asks through Playwright's client."""
        if self.is_client(source, expr, scope):
            return True
        return method == "fetch" and isinstance(expr, ast.Name) and \
            self._named(self.routes, source, expr.id, scope)

    # -- learning it, until nothing new is learned -----------------------------------

    def _settle(self):
        while True:
            learned = False
            for source in self.sources.values():
                for node in source.facts:
                    learned |= self._learn(source, node)
            if not learned:
                return

    def _bind(self, source, scope, target, holds: bool) -> bool:
        if not holds:
            return False
        if isinstance(target, ast.Name):
            names = self.names[(source.name, scope)]
            if target.id not in names:
                names.add(target.id)
                return True
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                and target.value.id in ("self", "cls"):
            if target.attr not in self.attrs[source.name]:
                self.attrs[source.name].add(target.attr)
                return True
        elif isinstance(target, (ast.Tuple, ast.List)):
            return any([self._bind(source, scope, t, True) for t in target.elts])
        return False

    def _learn(self, source, node) -> bool:
        scope = source.scope_of(node)
        holds = lambda expr: self.is_client(source, expr, scope)  # noqa: E731
        learned = False
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, (ast.Tuple, ast.List)) and \
                        isinstance(node.value, (ast.Tuple, ast.List)) and \
                        len(target.elts) == len(node.value.elts):
                    for t, v in zip(target.elts, node.value.elts):
                        learned |= self._bind(source, scope, t, holds(v))
                else:
                    learned |= self._bind(source, scope, target, holds(node.value))
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            learned |= self._bind(source, scope, node.target, holds(node.value))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    learned |= self._bind(source, scope, item.optional_vars,
                                          holds(item.context_expr))
        elif isinstance(node, (ast.For, ast.AsyncFor)) and \
                isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            learned |= self._bind(source, scope, node.target,
                                  any(holds(e) for e in node.iter.elts))
        elif isinstance(node, ast.Return) and node.value is not None:
            if isinstance(scope, DEFS) and scope not in self.returns and holds(node.value):
                self.returns.add(scope)
                learned = True
        elif isinstance(node, ast.Call):
            learned |= self._hand_over(source, node, scope)
            learned |= self._route_handler(source, node)
        return learned

    def _hand_over(self, source, call, scope) -> bool:
        """A client handed to a function makes its parameter one."""
        learned = False
        given = []
        for i, arg in enumerate(call.args):
            if isinstance(arg, ast.Starred):
                break
            if self.is_client(source, arg, scope):
                given.append((i, None))
        given += [(None, k.arg) for k in call.keywords
                  if k.arg and self.is_client(source, k.value, scope)]
        if not given:
            return False
        for there, fn in self.functions_called(source, call.func):
            positional = [a.arg for a in fn.args.posonlyargs + fn.args.args]
            if positional and positional[0] in ("self", "cls") and \
                    isinstance(call.func, ast.Attribute):
                positional = positional[1:]
            for i, keyword in given:
                if keyword is not None:
                    known = positional + [a.arg for a in fn.args.kwonlyargs]
                    name = keyword if keyword in known else None
                else:
                    name = positional[i] if i < len(positional) else None
                if name is None:
                    continue
                names = self.names[(there.name, fn)]
                if name not in names:
                    names.add(name)
                    learned = True
                if (source.name, call.lineno, fn.name) not in \
                        [(s.name, c.lineno, f.name) for s, c, f in self.handed]:
                    self.handed.append((source, call, fn))
        return learned

    def _route_handler(self, source, call) -> bool:
        """The first parameter of a function handed to route() holds a Route."""
        f = call.func
        if not (isinstance(f, ast.Attribute) and f.attr == "route"):
            return False
        handler = call.args[1] if len(call.args) > 1 else \
            next((k.value for k in call.keywords if k.arg == "handler"), None)
        if isinstance(handler, ast.Lambda):
            found = [(source, handler)]
        elif handler is not None:
            found = self.functions_called(source, handler)
        else:
            found = []
        learned = False
        for there, fn in found:
            params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
            if params and params[0] in ("self", "cls"):
                params = params[1:]
            if params and params[0] not in self.routes[(there.name, fn)]:
                self.routes[(there.name, fn)].add(params[0])
                learned = True
        return learned

    # -- what the census answers ------------------------------------------------------

    def calls(self):
        """(module, call, its function) for every call into the client."""
        out = []
        for source in self.sources.values():
            for node in ast.walk(source.tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr in SENDS:
                    scope = source.scope_of(node)
                    if self.sends_through(source, node.func.value, scope, node.func.attr):
                        out.append((source, node, scope))
        return out

    def unchecked(self) -> list:
        """Every call that could follow a redirect by itself, and every
        sending method taken off a client without being called."""
        out = []
        for source, call, _scope in self.calls():
            wrong = _redirects_it_follows(call)
            if wrong:
                out.append("%s:%d %s" % (source.name, call.lineno, wrong))
        for source in self.sources.values():
            for node in ast.walk(source.tree):
                scope = source.scope_of(node)
                if isinstance(node, ast.Attribute) and node.attr in SENDS:
                    parent = source.parent.get(node)
                    if isinstance(parent, ast.Call) and parent.func is node:
                        continue
                    if self.sends_through(source, node.value, scope, node.attr):
                        out.append("%s:%d .%s is taken off a client without being called, "
                                   "so what it follows cannot be read"
                                   % (source.name, node.lineno, node.attr))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                        node.func.id == "getattr" and len(node.args) >= 2 and \
                        isinstance(node.args[1], ast.Constant) and node.args[1].value in SENDS \
                        and self.is_client(source, node.args[0], scope):
                    out.append("%s:%d getattr takes .%s off a client, so what it follows "
                               "cannot be read" % (source.name, node.lineno, node.args[1].value))
        return sorted(out)

    def location_reads(self) -> list:
        """Every place outside the core helper that reads a Location header."""
        out = []
        for source in self.sources.values():
            if source.name == WALKER:
                continue
            for node in ast.walk(source.tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and node.value.strip().lower() == "location"):
                    continue
                parent = source.parent.get(node)
                read = (isinstance(parent, ast.Subscript) and parent.slice is node) or \
                    (isinstance(parent, ast.Call) and parent.args and parent.args[0] is node
                     and isinstance(parent.func, ast.Attribute)
                     and parent.func.attr in HEADER_READS) or \
                    (isinstance(parent, ast.Compare) and parent.left is node
                     and any(isinstance(o, (ast.In, ast.NotIn)) for o in parent.ops))
                if read:
                    out.append("%s:%d reads where a redirect points, which only %s may do"
                               % (source.name, node.lineno, WALKER))
        return sorted(out)


def _redirects_it_follows(call) -> str:
    """Why a call into the client could follow a redirect, or nothing.
    Every keyword of the client's is keyword-only, and a max_redirects in a
    ** beside an explicit one is refused by Python itself."""
    for k in call.keywords:
        if k.arg == "max_redirects":
            v = k.value
            if isinstance(v, ast.Constant) and type(v.value) is int and v.value == 0:
                return ""
            return ".%s passes max_redirects=%s, so it follows redirects nobody checked" \
                % (call.func.attr, ast.unparse(v))
    return ".%s passes no max_redirects=0, so Playwright follows up to twenty redirects " \
        "with the browser's cookies and checks none" % call.func.attr


def census_of(sources) -> Census:
    return Census([Source(name, text) for name, text in sources])


def _on_disk():
    paths = sorted(REPO.glob("apps/*/*.py")) + sorted(REPO.glob("core/paperpull_core/*.py"))
    return [(p.relative_to(REPO).as_posix(), p.read_text(encoding="utf-8")) for p in paths]


CENSUS = census_of(_on_disk())


def _function_name(scope) -> str:
    return getattr(scope, "name", "<lambda>") if scope is not None else "<module>"


# -- the repository ------------------------------------------------------------------

def test_every_call_into_the_request_client_follows_no_redirect_by_itself():
    found = CENSUS.unchecked()
    assert not found, (
        "Each of these asks through Playwright's own client, with the browser's "
        "cookies, and could follow a redirect to any host. Pass max_redirects=0, "
        "or ask through paperpull_core.redirects.get with the app's guard.\n  "
        + "\n  ".join(found))


def test_only_the_core_helper_reads_where_a_redirect_points():
    """A redirect followed by hand anywhere else is followed without the
    check, so reading its Location is the core helper's alone."""
    found = CENSUS.location_reads()
    assert not found, "\n  ".join(found)


def test_the_census_reaches_the_calls_it_is_about():
    """It does not pass for want of finding anything. The core helper's own
    ask is reached only through the parameter every caller hands a client
    to, and the rest are the ones that ask directly."""
    calls = {(s.name, _function_name(scope)) for s, _c, scope in CENSUS.calls()}
    assert (WALKER, "get") in calls
    assert ("core/paperpull_core/capture.py", "take_same_tab") in calls
    apps = {name.split("/")[1] for name, _fn in calls if name.startswith("apps/")}
    handed = {s.name.split("/")[1] for s, _c, fn in CENSUS.handed
              if fn.name == "get" and s.name.startswith("apps/")}
    assert len(calls) >= 15, sorted(calls)
    assert len(apps | handed) >= 18, sorted(apps | handed)
    assert len(handed) >= 7, sorted(handed)


# -- what the census sees, on made-up modules -------------------------------------------

APP = "apps/demo/demo_site.py"


def _unchecked(*sources):
    return [line.split(" ", 1)[0] for line in census_of(sources).unchecked()]


def test_a_plain_ask_is_named():
    text = "def f(page, u):\n    return page.context.request.get(u, timeout=1)\n"
    assert _unchecked((APP, text)) == [APP + ":2"]


def test_only_a_written_zero_will_do():
    for value in ("3", "20", "False", "None", "hops", "0.0"):
        text = "def f(page, u, hops):\n    return page.request.get(u, max_redirects=%s)\n" % value
        assert _unchecked((APP, text)) == [APP + ":2"], value
    text = "def f(page, u, kw):\n    return page.request.post(u, **kw)\n"
    assert _unchecked((APP, text)) == [APP + ":2"]
    text = "def f(page, u, kw):\n    return page.request.get(u, max_redirects=0, **kw)\n"
    assert _unchecked((APP, text)) == []


def test_every_method_that_sends_is_held_to_it():
    for method in SENDS:
        text = "def f(ctx, u):\n    return ctx.request.%s(u)\n" % method
        assert _unchecked((APP, text)) == [APP + ":2"], method


def test_a_client_kept_in_a_name_or_on_self_is_followed():
    text = ("def f(page, u):\n"
            "    rq = page.context.request\n"
            "    return rq.get(u)\n")
    assert _unchecked((APP, text)) == [APP + ":3"]
    text = ("class A:\n"
            "    def __init__(self, page):\n"
            "        self.api = page.request\n"
            "    def ask(self, u):\n"
            "        return self.api.get(u)\n")
    assert _unchecked((APP, text)) == [APP + ":5"]
    text = ("def f(page, other, u):\n"
            "    for c in (page.request, other):\n"
            "        c.get(u)\n")
    assert _unchecked((APP, text)) == [APP + ":3"]


def test_a_client_handed_to_a_function_is_followed_into_it():
    text = ("def ask(client, u):\n"
            "    return client.get(u)\n"
            "def f(page, u):\n"
            "    return ask(page.context.request, u)\n")
    assert _unchecked((APP, text)) == [APP + ":2"]
    by_keyword = text.replace("ask(page.context.request, u)", "ask(u=u, client=page.request)")
    assert _unchecked((APP, by_keyword)) == [APP + ":2"]
    method = ("class A:\n"
              "    def ask(self, client, u):\n"
              "        return client.get(u)\n"
              "    def run(self, page, u):\n"
              "        return self.ask(page.request, u)\n")
    assert _unchecked((APP, method)) == [APP + ":3"]


def test_a_client_handed_into_the_core_is_followed_there():
    core = ("core/paperpull_core/helper.py",
            "def ask(c, u):\n    return c.get(u)\n")
    by_name = (APP, "from paperpull_core.helper import ask as _ask\n"
                    "def f(page, u):\n    return _ask(page.request, u)\n")
    assert _unchecked(core, by_name) == [core[0] + ":2"]
    by_module = (APP, "from paperpull_core import helper\n"
                      "def f(page, u):\n    return helper.ask(page.request, u)\n")
    assert _unchecked(core, by_module) == [core[0] + ":2"]
    relative = ("core/paperpull_core/capture.py",
                "from . import helper\n"
                "def f(page, u):\n    return helper.ask(page.context.request, u)\n")
    assert _unchecked(core, relative) == [core[0] + ":2"]
    not_handed = (APP, "from paperpull_core.helper import ask\n"
                       "def f(d, u):\n    return ask(d, u)\n")
    assert _unchecked(core, not_handed) == []


def test_a_client_an_app_module_hands_to_its_site_module_is_followed():
    site = (APP, "def ask(c, u):\n    return c.get(u)\n")
    docs = ("apps/demo/demo_docs.py",
            "import demo_site as site\n"
            "def f(page, u):\n    return site.ask(page.request, u)\n")
    assert _unchecked(site, docs) == [APP + ":2"]


def test_a_client_a_function_hands_back_is_followed():
    text = ("def client(page):\n"
            "    return page.context.request\n"
            "def f(page, u):\n"
            "    return client(page).get(u)\n")
    assert _unchecked((APP, text)) == [APP + ":4"]


def test_a_client_of_its_own_is_one_too():
    text = ("def f(p, u):\n"
            "    api = p.request.new_context()\n"
            "    return api.get(u)\n")
    assert _unchecked((APP, text)) == [APP + ":3"]
    text = ("def f(p, u):\n"
            "    with p.request.new_context() as api:\n"
            "        return api.get(u)\n")
    assert _unchecked((APP, text)) == [APP + ":3"]
    text = "def f(page, u):\n    return getattr(page, 'request').get(u)\n"
    assert _unchecked((APP, text)) == [APP + ":2"]


def test_a_route_handlers_fetch_is_held_to_it():
    text = ("def f(page):\n"
            "    page.route('**/*', lambda route: route.fulfill(response=route.fetch()))\n")
    assert _unchecked((APP, text)) == [APP + ":2"]
    text = ("def handler(route):\n"
            "    route.fulfill(response=route.fetch(max_redirects=0))\n"
            "def other(route):\n"
            "    route.fulfill(response=route.fetch())\n"
            "def f(page):\n"
            "    page.route('**/*', handler)\n"
            "    page.context.route('**/*', handler=other)\n")
    assert _unchecked((APP, text)) == [APP + ":4"]


def test_a_method_taken_off_a_client_is_named():
    for line in ("fetch = page.request.get", "functools.partial(page.context.request.post, u)",
                 "getattr(page.request, 'get')(u)"):
        text = "import functools\ndef f(page, u):\n    %s\n" % line
        assert _unchecked((APP, text)) == [APP + ":3"], line


def test_what_is_not_a_client_is_left_alone():
    text = ("def on_response(res, seen, d):\n"
            "    seen.get(res.request)\n"
            "    d.get('x')\n"
            "    if res.request.method == 'GET':\n"
            "        return res.request.post_data\n"
            "def f(page, u):\n"
            "    return page.context.request.get(u, max_redirects=0, timeout=5)\n")
    assert _unchecked((APP, text)) == []


def test_a_location_read_outside_the_core_helper_is_named():
    for read in ("r.headers['location']", "r.headers.get('Location')",
                 "r.header_value('location')", "'location' in r.headers"):
        text = "def f(r):\n    return %s\n" % read
        assert [line.split(" ", 1)[0] for line in census_of([(APP, text)]).location_reads()] \
            == [APP + ":2"], read
        assert census_of([(WALKER, text)]).location_reads() == []
    text = "def f(page):\n    return page.evaluate('location.href')\n"
    assert census_of([(APP, text)]).location_reads() == []


def test_the_core_helpers_own_ask_is_reached_through_its_parameter():
    walker = (WALKER, (REPO / WALKER).read_text(encoding="utf-8"))
    caller = (APP, "from paperpull_core import redirects\n"
                   "def f(page, u, ok):\n"
                   "    return redirects.get(page.context.request, u, ok, timeout=5)\n")
    census = census_of([walker, caller])
    assert census.unchecked() == []
    assert [(s.name, _function_name(scope)) for s, _c, scope in census.calls()] == [(WALKER, "get")]
    hollow = (WALKER, walker[1].replace("max_redirects=0, ", ""))
    assert [line.split(" ", 1)[0].split(":")[0] for line in census_of([hollow, caller]).unchecked()] \
        == [WALKER]
