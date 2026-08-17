"""Shared core for the PaperPull downloaders.

Each app used to carry its own copy of these modules — 15,000-odd lines of
support code duplicated thirteen times, which meant every fix had to be made
thirteen times and copies quietly drifted apart. The logic lives here once;
an app declares an `AppSpec` describing what makes *it* different and keeps
only its orchestrator and its `*_site.py`.

Typical use, from an app's storage.py shim:

    from pathlib import Path
    from paperpull_core.spec import AppSpec, Folder, CsvSpec, DOCUMENT
    from paperpull_core import storage as _core

    SPEC = AppSpec(provider="T-Mobile", project_dir=Path(__file__).parent, ...)
    _core.bind(SPEC)
    from paperpull_core.storage import *      # the app's usual API
"""
from .spec import AppSpec, CsvSpec, DOCUMENT, Folder, INFRASTRUCTURE_FOLDERS, RECEIPT

__version__ = "0.1.1"

__all__ = ["AppSpec", "CsvSpec", "Folder", "INFRASTRUCTURE_FOLDERS",
           "RECEIPT", "DOCUMENT", "__version__"]
