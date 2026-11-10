"""Two configs beside each other that name one debugging port.

Each person's config names the debugging port of the browser they sign in
with, and a sign-in on a port a browser already holds joins that browser
(browser.open_signin_browser, #90). So two configs on one port sign in to
one browser, one profile, and a run of either reads whichever account that
browser is signed in to. tools/add_account.py gave a second person their
app's port plus 10, moved past the ports in use when they were added, so an
app set up after them could come with that same port. It now gives one a
port from PEOPLE_PORTS up, which no app comes with, but the people added
before then keep theirs, and a config copied by hand can name any port.

Nothing here changes a config or stops anything, since a wrong refusal is
worse than the clash. Login says so before it opens the sign-in window,
and the control panel says so on the account's row and page, each naming
the other install and account and the cdp_url to change. Only a person's
own config counts, config.json and each config.<label>.json. An install's
config.example.json is a template no run reads, and so is a copy of it a
sync service or Finder made that nobody filled in (is_example). A config
that names no port opens a browser of its own when it runs.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from .characters import whole_json
from .run_reporting import one_line

# How the launcher finds an install (paperpull.py list_apps and
# entry_script), a folder holding an app's entry script. tools/add_account.py
# reads the ports beside an app from the same folders.
ENTRY_RE = re.compile(r"[^.].*_(receipts|docs)\.py$")
EXAMPLE = "config.example.json"
# The names a sync service or Finder gives a copy of the example,
# "config.example 2.json" from iCloud or "config.example copy.json". A copy
# under one of them is no one's config only while nobody has filled it in
# (is_example), and the control panel lists accounts by the same test.
_EXAMPLE_COPY_RE = re.compile(r"config\.example(?: \d+| copy(?: \d+)?)?\.json", re.I)
# The settings that say where a config's runs sign in and save. A copy
# without one the example names runs somewhere of its own, since a config
# with no cdp_url opens a browser of its own.
_WHERE_KEYS = ("cdp_url", "output_dir", "profile_dir")
# Where a moved config goes, the range tools/add_account.py gives each person
# after the first (its PEOPLE_PORTS, which a test holds to this), above
# every port an app comes with.
PEOPLE_PORTS = 9400
# A config is a few hundred bytes. Anything far larger, or anything that is
# not a plain file, a pipe or a device say, is not read, since on PaperPull
# Server another install's folder is in a share other people can write to.
_MOST_BYTES = 1 << 20


class Named(NamedTuple):
    """One person's config and the port its cdp_url names."""
    config: Path
    port: int
    url: str


class Shared(NamedTuple):
    """A config whose port other configs beside it name too."""
    port: int
    others: List[Named]
    # Every config of the port but one, each with its cdp_url on a port of
    # its own. The one that keeps the port is the same whichever config of
    # the port is asked about, so every row and every sign-in agree.
    moves: List[Tuple[Named, str]]


def port_of(url) -> Optional[int]:
    """The port a cdp_url names, or None."""
    if not isinstance(url, str):
        return None
    try:
        port = urlsplit(url.strip()).port
    except ValueError:
        port = None
    if port:
        return port
    # What browser.port_from_cdp_url reads, for a text that is not a whole
    # URL. [::1]:9240 is read whole above, never as port 1.
    m = re.search(r":(\d+)", url)
    return int(m.group(1)) if m and "[" not in url else None


def installs_in(root) -> List[Path]:
    """The installs in a folder, found as paperpull.list_apps finds them."""
    try:
        folders = sorted(Path(root).iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [d for d in folders if d.is_dir() and _entry(d)]


def _entry(folder: Path) -> str:
    """The name of an install's entry script, as paperpull.entry_script
    finds it, which names the app whatever its folder is called, or ""."""
    try:
        return next((p.name for p in sorted(folder.glob("*.py"))
                     if ENTRY_RE.match(p.name) and "test" not in p.name), "")
    except OSError:
        return ""


def shipped_folders() -> List[Path]:
    """Where this copy of PaperPull keeps the providers it ships, whose
    ports a moved config must not take, since one set up later comes with
    its own. A checkout's apps folder, a package's templates/apps beside its
    own Python (python/python.exe on Windows, python/bin/python3 in the Mac
    app), and the folder holding the running app's own code, which is the
    image's apps on PaperPull Server. A folder that is not there is left
    out."""
    here = Path(__file__).resolve()
    exe = Path(sys.executable).resolve()
    places = [here.parents[2] / "apps"]
    places += [base / "templates" / "apps" for base in exe.parents[1:3]]
    # The running app's code, from the spec its storage bound. Only an app
    # run has one, and the control panel, which has none, never loads it.
    storage = sys.modules.get(__package__ + ".storage")
    try:
        places.append(storage.spec().project_dir.parent)
    except Exception:
        pass
    return [p for p in places if p.is_dir()]


def configs_of(install: Path) -> List[Path]:
    """Every person's config in an install, config.json first, never the
    example or a copy of it nobody filled in (is_example)."""
    own = [install / "config.json"] if (install / "config.json").is_file() else []
    try:
        return own + [p for p in sorted(install.glob("config.*.json")) if not is_example(p)]
    except OSError:
        return own


def _settings_in(path: Path) -> Optional[dict]:
    """A config's settings, or None when it is not a plain file of a few
    hundred bytes holding one JSON object."""
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > _MOST_BYTES:
            return None
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return None
    return cfg if isinstance(cfg, dict) else None


def holds_only_the_example(copy: dict, example: dict) -> bool:
    """Whether a copy's settings are the example's, as nobody filled in.
    Every setting in it, comments aside, is one the example has, with the
    example's value, so a value changed or a setting added is somebody's.
    A setting the example gained since the copy was made is not counted,
    since an update adds those to the example and never to a copy, but a
    copy without the cdp_url, output_dir or profile_dir the example names
    runs somewhere of its own and is somebody's too."""
    own = {k: v for k, v in copy.items() if not str(k).startswith("//")}
    if any(k not in example or example[k] != v for k, v in own.items()):
        return False
    return all(k in own for k in _WHERE_KEYS if k in example)


def is_example(config) -> bool:
    """Whether a config beside an app is its example, config.example.json,
    or a copy of it a sync service or Finder made (_EXAMPLE_COPY_RE) that
    still holds only the example's settings (holds_only_the_example). None
    of those is a person's. A copy somebody filled in is theirs, and so is
    one that cannot be read, or whose example cannot, since a person's
    account hidden is never run and nothing says so."""
    config = Path(config)
    if config.name == EXAMPLE:
        return True
    if not _EXAMPLE_COPY_RE.fullmatch(config.name):
        return False
    copy = _settings_in(config)
    example = _settings_in(config.parent / EXAMPLE)
    return copy is not None and example is not None and holds_only_the_example(copy, example)


def account_of(config: Path) -> str:
    """The account a config is for, "primary" for config.json, as the
    control panel calls it, and otherwise its label."""
    name = Path(config).name
    return "primary" if name == "config.json" else name[len("config."):-len(".json")]


def _url_in(path: Path):
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > _MOST_BYTES:
            return None
        cfg = whole_json(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, RecursionError):
        return None
    return cfg.get("cdp_url") if isinstance(cfg, dict) else None


def _key(path) -> str:
    """One file however it is reached. A path that cannot be resolved, a
    link that leads to itself say, is taken as written, so one strange file
    never silences what is said of the others."""
    try:
        where = str(Path(path).resolve())
    except (OSError, RuntimeError):
        where = os.path.abspath(str(path))
    return os.path.normcase(where)


def key_of(config) -> str:
    """How findings keys a config."""
    return _key(config)


def findings(installs: Iterable[Path], shipped: Iterable[Path] = ()) -> Dict[str, Shared]:
    """Every config in these installs whose port another of them names,
    keyed by its resolved path, as key_of gives it. Each file is read once,
    so the control panel asks this once for all its rows. The providers in
    the shipped folders are ones a person may set up later, and a moved
    config is never told to take one of their ports."""
    installs = list(installs)
    named: List[Named] = []
    # Each example port with the apps, by entry script, that come with it,
    # and each install's own example port.
    shipping: Dict[int, set] = {}
    examples = {}
    for folder in {_key(f): f for f in shipped}.values():
        for example, entries in _shipping_in(folder).items():
            shipping.setdefault(example, set()).update(entries)
    for install in installs:
        example = port_of(_url_in(install / EXAMPLE))
        if example:
            examples[_key(install)] = (example, _entry(install))
            shipping.setdefault(example, set()).add(_entry(install))
        for config in configs_of(install):
            url = _url_in(config)
            port = port_of(url)
            if port:
                named.append(Named(config, port, url))
    by_port: Dict[int, List[Named]] = {}
    for n in named:
        by_port.setdefault(n.port, []).append(n)
    # Each port a moved config is told, as it is told. Lowest shared port
    # first, so three pairs followed as said end on three ports, not on one.
    told: set = set()
    found = {}
    for port in sorted(by_port):
        group = sorted(by_port[port], key=lambda n: _key(n.config))
        if len(group) < 2:
            continue
        keeps = _keeper(group, examples)
        moves = [(n, _moved(n, told, examples, shipping, by_port)) for n in group
                 if n is not keeps]
        for this in group:
            found[_key(this.config)] = Shared(port, [n for n in group if n is not this], moves)
    return found


# The ports the providers in a shipped folder come with, by the folder and
# the names in it. Shipped code changes only with an update, and the
# control panel asks on every page it loads, where reading 78 providers'
# examples each time made its rows late. Listing the names is quick, and
# they change as soon as a provider is added or taken out, which a
# folder's time on a coarse clock need not.
_SHIPPED: Dict[Tuple[str, Tuple[str, ...]], Dict[int, set]] = {}


def _shipping_in(folder: Path) -> Dict[int, set]:
    try:
        names = tuple(sorted(p.name for p in Path(folder).iterdir()))
    except OSError:
        return {}
    key = (_key(folder), names)
    if key not in _SHIPPED:
        found: Dict[int, set] = {}
        for template in installs_in(folder):
            example = port_of(_url_in(template / EXAMPLE))
            if example:
                found.setdefault(example, set()).add(_entry(template))
        _SHIPPED[key] = found
    return _SHIPPED[key]


def _keeper(group: List[Named], examples: dict) -> Named:
    """Which config of a shared port keeps it. One on its own app's example
    port first, since that port is the app's and a config moved or copied
    onto it is the one that strayed. Then a first person's config before a
    second person's, since a second person's port was chosen later. Then
    the first by its path, so a tie comes out the same from every side."""
    def rank(n: Named):
        own = examples.get(_key(n.config.parent), (None, ""))[0]
        return (own != n.port, n.config.name != "config.json", _key(n.config))
    return min(group, key=rank)


def _moved(n: Named, told: set, examples: dict, shipping: dict, by_port: dict) -> str:
    """n's cdp_url on a port of its own. A first person's config takes its
    app's own example port when no config names it, no other provider comes
    with it and no moved config has been told it, which is the port a new
    install of that app takes. Any other takes the first port from
    PEOPLE_PORTS up that no config or provider names and no moved config
    has been told, as tools/add_account.py gives a second person theirs, so
    the port it is told is never one an app set up later comes with. The
    port goes into told, so no other config is told to move to it."""
    port, entry = examples.get(_key(n.config.parent), (None, ""))
    if not (n.config.name == "config.json" and port and port not in by_port
            and port not in told and shipping.get(port, set()) <= {entry}):
        port = PEOPLE_PORTS
        while port in by_port or port in shipping or port in told:
            port += 1
    told.add(port)
    return re.sub(r":%d\b" % n.port, ":%d" % port, n.url, count=1)


def shared_at(config) -> Optional[Shared]:
    """What another config beside this one shares with it, or None. The
    installs are the ones in the folder that holds this config's install,
    its own included."""
    config = Path(config)
    if not config.is_file():
        return None
    install = config.parent
    installs = installs_in(install.parent)
    if _key(install) not in {_key(d) for d in installs}:
        installs.append(install)
    return findings(installs, shipped_folders()).get(_key(config))


def who(n: Named) -> str:
    """An install and account, as a sentence names them."""
    account = account_of(n.config)
    folder = one_line(n.config.parent.name)
    return ("the first account of " + folder if account == "primary"
            else 'the "%s" account of %s' % (one_line(account), folder))


def say_at_sign_in(config, port) -> None:
    """At Login, before the sign-in window opens, say which other configs
    beside this one name the port it opens on and which cdp_url to change.
    Only said, never asked, and the sign-in goes on whatever this finds."""
    if config is None:
        return
    found = shared_at(config)
    if found is None or str(found.port) != str(port).strip():
        return
    this = _key(config)
    many = len(found.others)
    print("!! %s beside this one %s port %d too."
          % ("Another config" if many == 1 else "%d other configs" % many,
             "names" if many == 1 else "name", found.port))
    for n in found.others:
        print("     %s (%s)" % (who(n), one_line(n.config.name)))
    one = len(found.moves) == 1
    print("   A sign-in on a port that is in use joins the browser already there, so")
    print("   these accounts sign in to one browser, and a run of any of them reads")
    print("   whichever account that browser is signed in to. To keep them apart,")
    print("   give %s below a port of its own by changing its cdp_url to the address"
          % ("the config" if one else "each config"))
    print("   under it, %s no other config here names and no provider PaperPull ships"
          % ("a port" if one else "ports"))
    print("   comes with.")
    for n, to in found.moves:
        print("     %s%s" % (one_line(n.config), " (this config)" if _key(n.config) == this else ""))
        print("       %s" % one_line(to))
    print("   Nothing is stopped for this, and the sign-in goes on.")
    print()
