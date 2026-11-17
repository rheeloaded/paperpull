"""A browser named by its brand (#222) opens on a profile folder beside the
account's usual one, "chase-browser-profile-googlechrome" beside
"chase-browser-profile", and the panel knows it as a signed-in profile too.
So it is never taken as a documents folder, nor a folder around it or in
it, and nothing in it is read as a document of the account's.
"""
from pathlib import Path

import pytest

app_module = pytest.importorskip("app")
import server_mode  # noqa: E402

ENDINGS = ("-microsoftedge", "-googlechrome", "-brave", "-vivaldi", "-opera")


@pytest.fixture()
def bank(monkeypatch, tmp_path):
    install = tmp_path / "Chase"
    install.mkdir()
    monkeypatch.setattr(server_mode, "enabled", lambda: False)
    monkeypatch.setattr(app_module, "_config_of",
                        lambda meta, account: {"profile_dir": "chase-browser-profile"})
    meta = {"dir": str(install), "accounts": ["primary"]}
    return install, meta


@pytest.mark.parametrize("ending", ENDINGS)
def test_a_brand_folder_is_a_profile_the_panel_knows(ending, bank):
    install, meta = bank
    known = {Path(p).resolve() for p in app_module._profiles_known({"Chase": meta})}
    assert (install / ("chase-browser-profile" + ending)).resolve() in known
    assert (install / "chase-browser-profile").resolve() in known


@pytest.mark.parametrize("ending", ENDINGS)
def test_a_brand_folder_is_never_where_documents_are(ending, bank):
    install, meta = bank
    kept = {Path(p).resolve() for p in app_module._not_for_documents(meta, "primary")}
    assert (install / ("chase-browser-profile" + ending)).resolve() in kept


@pytest.mark.parametrize("ending", ENDINGS)
def test_a_brand_folder_cannot_be_chosen_as_the_documents_folder(ending, bank):
    install, meta = bank
    folder = install / ("chase-browser-profile" + ending)
    folder.mkdir()
    said = app_module._documents_problem({"Chase": meta}, "Chase", "primary", str(folder / "Docs"))
    assert said and "browser profile" in said


def test_a_folder_that_only_starts_the_same_is_not_a_profile(bank):
    install, meta = bank
    known = {Path(p).resolve() for p in app_module._profiles_known({"Chase": meta})}
    assert (install / "chase-browser-profile-spouse").resolve() not in known
