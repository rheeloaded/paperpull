"""Every app files its kinds the way the kind_folders refusal assumes (#201).

Without kind folders, documents of every kind an app files share one
folder, so the setting is refused unless a field of the naming pattern
says which kind a document is (storage.fields_telling_kinds_apart). That
holds only when the folder of a document's kind follows from the field's
value. A statements app routes by the record's category and names passing
no kind, so a pattern's {kind} is that category. A receipts app routes by
the purchase type, {type}, and files invoices by their document type,
{kind}. An app that files a kind by name some other way has no such field
and is refused outright.

This reads each app's own code for that, so an app that starts filing a
kind another way fails here rather than letting two kinds want one name.
"""
import ast
import importlib.util
from pathlib import Path

import pytest

from paperpull_core import storage as core_storage
from paperpull_core.spec import INFRASTRUCTURE_FOLDERS, RECEIPT

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(p.parent for p in (REPO / "apps").glob("*/storage.py"))
IDS = [a.name for a in APPS]
KEPT = {f.attr for f in INFRASTRUCTURE_FOLDERS}


@pytest.fixture
def loaded(monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))

    def load(app: Path):
        found = importlib.util.spec_from_file_location("_kinds_of_%s" % app.name,
                                                       app / "storage.py")
        module = importlib.util.module_from_spec(found)
        found.loader.exec_module(module)
        return module.SPEC
    return load


def calls(app: Path):
    """Each call in the app's own code, its tests and storage.py left out,
    with the file it is in."""
    for path in sorted(app.glob("*.py")):
        if path.name == "storage.py" or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                yield path.name, node


def called(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def kind_folders_used_directly(app: Path, attrs) -> list:
    """Each paths.<folder> of a kind the app's code names, which files
    there without routing."""
    found = []
    for path in sorted(app.glob("*.py")):
        if path.name == "storage.py" or path.name.startswith("test_"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Attribute) and node.attr in attrs
                    and isinstance(node.value, ast.Attribute) and node.value.attr == "paths"):
                found.append("%s:%d paths.%s" % (path.name, node.lineno, node.attr))
    return found


def test_there_are_apps_to_look_at():
    assert len(APPS) > 90


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_app_files_its_kinds_as_the_refusal_assumes(app, loaded):
    spec = loaded(app)
    need = core_storage.fields_telling_kinds_apart(spec)
    kinds = [f.attr for f in spec.folders if f.attr not in KEPT]
    if need is None:
        # Refused whatever the pattern says, so nothing more to hold it to.
        routed = set(spec.routes.values()) | {spec.default_route}
        assert any(k not in routed for k in kinds)
        return
    if not need:
        assert len(kinds) == 1
        return
    wrong = []
    for name, node in calls(app):
        what = called(node)
        if what == "folder_for":
            first = node.args[0] if node.args else None
            wanted = "purchase_type" if spec.kind == RECEIPT else "category"
            if not (isinstance(first, ast.Attribute) and first.attr == wanted):
                wrong.append("%s:%d folder_for(%s)" % (name, node.lineno, ast.unparse(first)))
        elif what == "build_pdf_filename" and spec.kind != RECEIPT:
            # No kind passed, so a pattern's {kind} is the record's category.
            kind = node.args[2] if len(node.args) > 2 else None
            if not (isinstance(kind, ast.Constant) and kind.value == "") \
                    or any(k.arg == "document_type" for k in node.keywords):
                wrong.append("%s:%d build_pdf_filename kind %s"
                             % (name, node.lineno, ast.unparse(kind) if kind else "Receipt"))
    assert not wrong, ("%s routes or names a kind another way than the kind_folders "
                       "refusal assumes: %s" % (app.name, wrong))
    direct = kind_folders_used_directly(app, set(kinds))
    if spec.kind == RECEIPT:
        # An invoice is filed in its folder directly, and told apart by its
        # kind, Invoice, which the refusal asks the pattern for.
        direct = [d for d in direct if not d.endswith("paths.invoices")]
        if "invoices" in kinds:
            assert "kind" in need
    assert not direct, ("%s files in a folder of a kind directly, which the kind_folders "
                        "refusal does not know of: %s" % (app.name, direct))


@pytest.mark.parametrize("app", ["target", "walmart"])
def test_an_invoice_is_named_as_one(app):
    """What lets {kind} tell an invoice from a receipt of the same order."""
    src = (REPO / "apps" / app / ("%s_receipts.py" % app)).read_text(encoding="utf-8")
    assert '"Invoice"' in src


def test_anthem_is_refused_and_a_statements_app_needs_its_kind(loaded):
    assert core_storage.fields_telling_kinds_apart(loaded(REPO / "apps" / "anthem")) is None
    assert core_storage.fields_telling_kinds_apart(loaded(REPO / "apps" / "pge")) == ["kind"]
    assert core_storage.fields_telling_kinds_apart(loaded(REPO / "apps" / "costco")) == ["type"]
    assert core_storage.fields_telling_kinds_apart(loaded(REPO / "apps" / "target")) == \
        ["type", "kind"]
    assert core_storage.fields_telling_kinds_apart(loaded(REPO / "apps" / "amazon")) == []
