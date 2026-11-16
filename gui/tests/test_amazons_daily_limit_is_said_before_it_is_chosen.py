"""Amazon's daily limit is said where a person chooses Amazon.

Amazon opens at most a day's orders (#229), so a long history takes days
or weeks of daily runs. Each run says so, but nothing a person reads before
setting Amazon up did. The panel's provider list, PROVIDERS.md (which
paperpull.net builds its cards from) and the README now say so, and each
names the number the app uses, so a change to the limit cannot leave one of
them saying the old one.
"""
import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AMAZON = REPO / "apps" / "amazon"


def _limit() -> int:
    """orders_per_day as storage.py's AppSpec gives it to every install,
    read without importing the app."""
    tree = ast.parse((AMAZON / "storage.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "config_defaults":
            return ast.literal_eval(node.value)["orders_per_day"]
    raise AssertionError("apps/amazon/storage.py gives no config_defaults")


def _says_the_limit(text: str) -> bool:
    return re.search(r"\bat most %d orders a day\b" % _limit(), text, re.IGNORECASE) is not None


def _row(name: str) -> list:
    """The cells of the amazon row of a provider table."""
    rows = [line for line in (REPO / name).read_text(encoding="utf-8").splitlines()
            if line.startswith("| [`amazon`]")]
    assert len(rows) == 1, (name, rows)
    return [cell.strip() for cell in rows[0].split("|")]


def test_a_new_install_and_the_app_use_one_limit():
    example = json.loads((AMAZON / "config.example.json").read_text(encoding="utf-8"))
    assert example["orders_per_day"] == _limit() > 0


def test_the_panels_provider_list_says_it():
    card = json.loads((REPO / "gui" / "providers.json").read_text(encoding="utf-8"))["providers"]["amazon"]
    assert _says_the_limit(card.get("note", "")), card


def test_paperpull_net_says_it_in_the_cards_note():
    """The site takes a Documents cell's first sentence as the document list
    and the rest as the card's note (paperpull-site gen_providers.clean_docs),
    so the limit is said after the list, never in it."""
    docs = _row("PROVIDERS.md")[4]
    listed, rest = re.split(r"[.;](?=\s|$)", docs, maxsplit=1)
    assert listed == "Order invoices (full history)", docs
    assert _says_the_limit(rest), docs


def test_the_readme_says_it():
    assert _says_the_limit(_row("README.md")[5])
