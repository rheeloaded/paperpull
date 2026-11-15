"""What makes one PaperPull app different from another.

Every app used to carry its own ~430-line copy of `storage.py` and friends.
Comparing those copies showed they were 94-100% identical once the provider's
name was normalized away; the real differences were always the same handful of
*facts*, not logic:

  * the provider's display name,
  * which folders it files documents into, and which of those it actually
    fills (so the rest are only created on demand),
  * how a document routes to a folder,
  * the CSV files it writes and their columns,
  * a few config defaults.

`AppSpec` is that handful of facts. An app declares one; the shared core does
everything else. Adding a provider means writing a spec, not copying a module.

Two families exist and both are first-class:

  RECEIPT apps  route by *purchase type*   ("Online" / "In-Store")
  DOCUMENT apps route by *category*        ("Statement" / "Tax Document" / ...)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RECEIPT = "receipt"
DOCUMENT = "document"

# A domain an AppSpec's url_settings names, such as ultipro.com.
_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", re.ASCII)


@dataclass(frozen=True)
class Folder:
    """One output folder.

    `precreate=False` means the folder is reachable through routing but is not
    created up front, it appears the moment a document actually lands there.
    That is what keeps an install from growing folders it can never fill (an
    `Insurance Documents` folder under a phone carrier, say).
    """

    attr: str          # attribute name on Paths, e.g. "tax_documents"
    name: str          # folder name on disk, e.g. "Tax Documents"
    precreate: bool = True


@dataclass(frozen=True)
class CsvSpec:
    attr: str          # attribute name on Paths, e.g. "document_index_csv"
    filename: str      # "{provider} Document Index.csv" - {provider} is filled in
    columns: List[str]


@dataclass
class AppSpec:
    """Everything the shared core needs to serve one provider."""

    provider: str                     # display name, e.g. "T-Mobile"
    # The app's own folder, the anchor for its DATA, its config.json, its
    # rules file, its browser profile default and the folders it files into.
    # Never used to locate code to import or run, that is Python's import
    # path. On the desktop the code and the data sit together, so this is
    # the install folder. On PaperPull Server the code is loaded from the
    # read-only image and only the data lives in the writable /data share,
    # so __post_init__ repoints this to PAPERPULL_DATA_DIR, the install's
    # data folder, while the code keeps coming from the image.
    project_dir: Path
    kind: str = DOCUMENT              # RECEIPT or DOCUMENT

    folders: List[Folder] = field(default_factory=list)
    # routing key -> Folder.attr. Keys are purchase types for RECEIPT apps
    # and categories for DOCUMENT apps.
    routes: Dict[str, str] = field(default_factory=dict)
    # where anything unrouted goes; None means "refuse to guess" (receipt apps
    # always route, so they leave this unset)
    default_route: Optional[str] = None

    csv_files: List[CsvSpec] = field(default_factory=list)
    config_defaults: Dict[str, object] = field(default_factory=dict)
    # A config setting that holds the address of the provider's site, with
    # the domains its host may sit under. PaperPull Server reads config.json
    # from a shared folder, so there a run stops unless such a setting is
    # an https address on a name under one of them. The desktop reads the
    # setting as written. UKG's base_url is one, since every employer has
    # its own UKG name.
    url_settings: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    # Used by the PDF validator to confirm a saved file is really this
    # provider's document. Defaults to the provider name, lowercased and
    # stripped of punctuation.
    pdf_token: Optional[str] = None
    # Host used as <base href> when re-rendering a saved HTML snapshot.
    base_url: Optional[str] = None
    # Rules file for item/document classification, relative to project_dir.
    rules_filename: Optional[str] = None

    # The countries whose accounts this app is for, as ISO 3166 codes from
    # core countries.NAMES, such as ("US",) or ("DE",). The panel's provider
    # list, PROVIDERS.md, the README and the website say them as
    # countries.label does, and read them from this file's source without
    # running it, so they are written as a plain tuple of strings.
    countries: Tuple[str, ...] = ()
    # True for a service with one site worldwide, built on an account in its
    # one country, which may well work for an account elsewhere.
    may_work_elsewhere: bool = False
    # For a provider with a separate store per country, each store's site and
    # its country, and the config setting that names the one an install
    # reads. Setting up such a provider in the panel asks which store.
    stores: Dict[str, str] = field(default_factory=dict)
    store_setting: Optional[str] = None

    def __post_init__(self):
        self.project_dir = Path(self.project_dir)
        # On PaperPull Server the data anchor is the install's folder in the
        # /data share, handed to the run by the panel, never where the code
        # being run happens to sit (which is the read-only image). Gated on
        # both variables, so a desktop process and any server process that
        # was not given a data folder are left exactly as the app declared.
        if os.environ.get("PAPERPULL_SERVER") == "1":
            data_dir = os.environ.get("PAPERPULL_DATA_DIR")
            if data_dir:
                self.project_dir = Path(data_dir)
        if self.kind not in (RECEIPT, DOCUMENT):
            raise ValueError(f"AppSpec.kind must be {RECEIPT!r} or {DOCUMENT!r}")
        seen_attrs = [f.attr for f in self.folders]
        if len(seen_attrs) != len(set(seen_attrs)):
            raise ValueError("duplicate folder attr in AppSpec.folders")
        known = set(seen_attrs)
        for key, attr in self.routes.items():
            if attr not in known:
                raise ValueError(
                    f"AppSpec.routes[{key!r}] points at unknown folder {attr!r}")
        if self.default_route and self.default_route not in known:
            raise ValueError(
                f"AppSpec.default_route {self.default_route!r} is not a declared folder")
        for key, domains in self.url_settings.items():
            # A tuple of plain domain names, since a string would be read
            # one letter at a time and a pattern or a URL is not a domain.
            if not (isinstance(domains, tuple) and domains
                    and all(isinstance(d, str) and _DOMAIN.fullmatch(d) for d in domains)):
                raise ValueError(
                    f"AppSpec.url_settings[{key!r}] must be a tuple of plain lowercase "
                    f"domain names, such as ('example.com',)")
        from . import countries as _countries
        _countries.check(self.countries, self.may_work_elsewhere, self.stores,
                         self.store_setting)

    @property
    def slug(self) -> str:
        """Lowercase, punctuation-free provider name (e.g. 't-mobile' -> 'tmobile')."""
        return "".join(ch for ch in self.provider.lower() if ch.isalnum())

    @property
    def token(self) -> str:
        return self.pdf_token if self.pdf_token is not None else self.slug

    @property
    def rules_path(self) -> Optional[Path]:
        if not self.rules_filename:
            return None
        return self.project_dir / self.rules_filename

    def folder(self, attr: str) -> Folder:
        for f in self.folders:
            if f.attr == attr:
                return f
        raise KeyError(attr)


# ---------------------------------------------------------------------------
# The folder sets every app shares
# ---------------------------------------------------------------------------

# Written to directly by the app (logging opens a file in Logs before anything
# routes), so these are always pre-created.
INFRASTRUCTURE_FOLDERS = [
    Folder("manual_review", "Manual Review"),
    Folder("logs", "Logs"),
    Folder("diagnostics", "Diagnostics"),
    Folder("backups", "Backups"),
]
