"""What makes one PaperPull app different from another.

Every app used to carry its own ~430-line copy of `storage.py` and friends.
Comparing those copies showed they were 94-100% identical once the provider's
name was normalised away; the real differences were always the same handful of
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

RECEIPT = "receipt"
DOCUMENT = "document"


@dataclass(frozen=True)
class Folder:
    """One output folder.

    `precreate=False` means the folder is reachable through routing but is not
    created up front — it appears the moment a document actually lands there.
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
    project_dir: Path                 # the app's own folder
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

    # Used by the PDF validator to confirm a saved file is really this
    # provider's document. Defaults to the provider name, lowercased and
    # stripped of punctuation.
    pdf_token: Optional[str] = None
    # Host used as <base href> when re-rendering a saved HTML snapshot.
    base_url: Optional[str] = None
    # Rules file for item/document classification, relative to project_dir.
    rules_filename: Optional[str] = None

    def __post_init__(self):
        self.project_dir = Path(self.project_dir)
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
