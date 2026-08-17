# paperpull-core

The shared support code behind every PaperPull app: filesystem layout, safe
filenames, atomic JSON/CSV writes, PDF capture and validation, and the local
classification rules engine.

Each app used to carry its own copy of all of this — about **15,000 lines
duplicated across thirteen apps**, so every fix had to be repeated thirteen
times and the copies drifted apart. This package holds that logic once.

## What stays in an app

An app keeps only what is genuinely its own:

| File | What it is |
|------|------------|
| `<provider>_site.py` | every selector, URL and page behaviour — the file you repair when a site changes |
| `<provider>_docs.py` / `_receipts.py` | the run orchestrator |
| `storage.py` | a small shim declaring this provider's `AppSpec` |
| `config.json`, rules JSON | per-install settings and tunable keywords |

## Declaring a provider

`AppSpec` holds the handful of facts that actually differ between providers —
the display name, the folders it files into, how a document routes to one,
the CSV files and columns, and a few config defaults:

```python
from pathlib import Path
from paperpull_core.spec import AppSpec, Folder, CsvSpec, DOCUMENT, INFRASTRUCTURE_FOLDERS
from paperpull_core import storage as _core

SPEC = AppSpec(
    provider="T-Mobile",
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

## Installing

Each app's `setup.bat` installs this into that app's own venv. From a repo
checkout:

```bat
.venv\Scripts\pip install -e ..\..\core
```

Standalone installs (outside the repo) install the vendored wheel instead:

```bat
.venv\Scripts\pip install core\paperpull_core-0.1.0-py3-none-any.whl
```

Pinning per install means updating the core is a deliberate act — a working
tool cannot break because something changed elsewhere.

## Tests

```bat
pytest
```
