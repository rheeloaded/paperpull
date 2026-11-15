# paperpull-core

The shared support code behind every PaperPull app: filesystem layout, safe
filenames, atomic JSON/CSV writes, PDF capture and validation, and the local
classification rules engine.

Each app used to carry its own copy of all of this, about **15,000 lines
duplicated across thirteen apps**, so every fix had to be repeated thirteen
times and the copies drifted apart. This package holds that logic once.

## What stays in an app

An app keeps only what is genuinely its own:

| File | What it is |
|------|------------|
| `<provider>_site.py` | every selector, URL and page behavior, the file you repair when a site changes |
| `<provider>_docs.py` / `_receipts.py` | the run orchestrator |
| `storage.py` | a small shim declaring this provider's `AppSpec` |
| `config.json`, rules JSON | per-install settings and tunable keywords |

## Declaring a provider

`AppSpec` holds the handful of facts that actually differ between providers,
the display name, the folders it files into, how a document routes to one,
the CSV files and columns, and a few config defaults:

```python
from pathlib import Path
from paperpull_core.spec import AppSpec, Folder, CsvSpec, DOCUMENT, INFRASTRUCTURE_FOLDERS
from paperpull_core import storage as _core

SPEC = AppSpec(
    provider="T-Mobile",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[Folder("statements", "Statements"),
             Folder("tax_documents", "Tax Documents"),
             # reachable, but only created if a document ever routes there
             Folder("other_documents", "Other Documents", precreate=False),
             *INFRASTRUCTURE_FOLDERS],
    routes={"Statement": "statements", "Tax Document": "tax_documents"},
    default_route="other_documents",
    ...
)
_core.bind(SPEC)
```

Two families are supported: **receipt** apps route by purchase type
(`Online` / `In-Store`), **document** apps route by category (`Statement`,
`Tax Document`, …).

A folder marked `precreate=False` is created the moment something routes
there, which is why an install never grows an empty folder for a document
type that provider cannot produce.

`countries` names the countries whose accounts the app is for, as ISO 3166
codes from `paperpull_core.countries.NAMES`, such as `("DE",)`. The panel's
provider list, PROVIDERS.md, the README and the website say them alike, and
the panel and the website read them from the source without running it, so
write them as a plain tuple of strings. Set `may_work_elsewhere=True` for a
service with one site worldwide that was built on an account in its one
country. A provider with a separate store per country, as Amazon has, lists
each store's site and country in `stores` and the config setting naming the
one an install reads in `store_setting`, and setting it up in the panel asks
which store. A census holds every app to all of this.

## Installing

In a repo checkout, setup-all installs this, editable, into `gui/.venv`, the
one environment the panel and every app share. An app's own `setup.bat`
installs it into that app's own venv the same way.

```bat
.venv\Scripts\pip install -e ..\..\core
```

Standalone installs (outside the repo) install the vendored wheel instead:

```bat
.venv\Scripts\pip install core\paperpull_core-0.1.0-py3-none-any.whl
```

Pinning per install means updating the core is a deliberate act, a working
tool cannot break because something changed elsewhere.

## Tests

```bat
pytest
```

That runs this package's own suite. To run everything in the repository,
the core, the control panel and every app, run this from the root.

```bat
python tools/run_all_tests.py
```

It runs several suites at a time, longest first, a quarter of the
processors by default (`--jobs N` to change it), and only one run at a
time on a machine, so a second run waits for the first and says whose it
is. `--stop` ends this checkout's run along with everything it started,
and `--replace` ends it and runs again.

The runner runs this package's tests as three suites, `core`,
`core-censuses` and `core-browsers`, so none of them is the one long suite
a run or a CI part waits for. `core-browsers` takes each test file whose
own code drives a real browser, `core-censuses` takes the censuses, the
files named `test_every_*` or `test_no_*`, and every other file stays in
`core`, the privacy canary included. `tools/pytest_plugins/core_part.py`
holds the rule. Plain `pytest` in this folder names none of them, so it
still runs every test. Through the runner, `--suites core` runs only the
files left in `core`, and `--suites core,core-censuses,core-browsers` runs
all three.

Several suites skip themselves when a library is missing, and a skip is a
quiet line nobody reads. One of them is `test_failure_canary.py`, the only
test holding the promise that a failure file carries no page content, and
it skips when Playwright is absent. So install the test extras:

```bat
pip install -e ".[test]"
python -m playwright install chromium
```

`run_all_tests.py` prints every skip at the end and refuses to report
success while the canary is one of them. Not being skipped is not enough
either. A run that holds the core suite passes only when every test of
the canary ran and passed, so a canary deleted, renamed or deselected
stops it too.

CI and the packaged app install the newest Playwright and the Chromium it
was made for, and two versions can differ in what a page hands over. So
`run_all_tests.py` runs each suite on the newest Playwright among the
environments here that can run it, says which version that was, and
refuses to report success when a suite that uses Playwright had to run on
an older one, or when that Playwright's own Chromium is not installed.
