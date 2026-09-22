"""The one redaction, and the proof no app has its own again.

A tester runs diagnose, reads the file, and attaches it to a public issue
because this project told them to. These are the promises that file makes.

This used to live in every app's *_site.py. Seventeen apps carried three
different versions of it, and five of those masked long digit runs and
nothing else, so a URL kept its query string, an amount stayed on screen
and the account holder's own name went through untouched. The test at the
bottom is what stops that happening twice.
"""
import re
from pathlib import Path

import pytest
from paperpull_core.redact import private_words, redact, set_private_words

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_owner():
    """Each test starts with no owner set, the state an app is in before
    its orchestrator reads a config."""
    set_private_words([])
    yield
    set_private_words([])


# -- what must never come through ---------------------------------------------

def test_a_url_loses_its_query_string_where_the_session_lives():
    out = redact("https://www.example.com/billing?token=abc123&acct=99887766")
    assert out == "https://www.example.com/billing?..."
    assert "token" not in out and "abc123" not in out


def test_a_long_digit_run_is_masked_wherever_it_appears():
    assert redact("Account 4455667788 ending") == "Account ########## ending"
    assert redact("/claims/20260101123456/view") == "/claims/##############/view"


def test_a_short_number_survives_because_a_survey_needs_dates_and_counts():
    for keep in ("March 2026", "1099-R", "12 bills", "Q3 2025", "page 4"):
        assert redact(keep) == keep, keep


def test_a_greeting_names_the_person_and_the_name_goes():
    assert redact("Welcome back, ALEX") == "Welcome back, [name]"
    assert redact("Hi Jane") == "Hi [name]"
    assert redact("Good evening, Sam Smith") == "Good evening, [name]"


def test_a_greeting_with_nobody_after_it_is_left_alone():
    assert redact("Welcome back") == "Welcome back"


def test_an_id_shaped_path_segment_goes():
    assert redact("https://x.example/accounts/d11-Kz9Rc8vQ7m/statements") == \
        "https://x.example/accounts/.../statements"


def test_a_readable_path_segment_stays_because_it_is_the_signal():
    url = "https://x.example/myaccount/billing/statements"
    assert redact(url) == url


def test_an_amount_is_a_balance_or_a_payment_and_goes():
    assert redact("Balance $1,234.56") == "Balance $x.xx"
    # The sign sits outside the amount, so it survives and reads right.
    assert redact("Total: -$45.00") == "Total: -$x.xx"
    for foreign in ("€1.234", "£99.99"):
        assert "$x.xx" in redact(foreign), foreign


def test_a_masked_tail_is_the_end_of_an_account_number():
    assert redact("Card ....1234") == "Card ....####"
    assert redact("Checking ••••8899") == "Checking ••••####"


# -- the owner's own name ------------------------------------------------------

def test_the_owner_name_goes_in_every_part_and_any_case():
    set_private_words(["Bryan Rhee"])
    assert redact("Bryan Rhee's documents") == "[name] [name]'s documents"
    assert redact("BRYAN") == "[name]"
    assert redact("welcome rhee") == "welcome [name]"


def test_a_title_or_suffix_is_not_a_name():
    set_private_words(["Dr Alex Chen Jr"])
    assert private_words() == ["Alex", "Chen"]
    assert redact("Dr visit") == "Dr visit"


def test_one_letter_initials_are_not_redacted_into_noise():
    set_private_words(["J Alex Chen"])
    assert "J" in private_words() or private_words() == ["Alex", "Chen"]
    assert private_words() == ["Alex", "Chen"]


def test_no_owner_set_still_redacts_everything_else():
    set_private_words([])
    assert redact("Balance $10.00 acct 123456789") == "Balance $x.xx acct #########"


def test_setting_the_owner_again_replaces_rather_than_accumulates():
    set_private_words(["Alex"])
    set_private_words(["Sam"])
    assert private_words() == ["Sam"]


def test_none_and_empty_are_survivable():
    set_private_words(None)
    assert redact(None) == ""
    assert redact("") == ""


# -- a real survey line, end to end --------------------------------------------

def test_a_line_carrying_several_at_once():
    set_private_words(["Bryan Rhee"])
    line = ("Hi Bryan, your account ....4321 balance $2,105.44 "
            "https://bank.example/acct/9M2kd7Qx1p/detail?sid=ZZZ 100200300")
    out = redact(line)
    for gone in ("Bryan", "4321", "2,105.44", "9M2kd7Qx1p", "sid", "ZZZ", "100200300"):
        assert gone not in out, gone


# -- and no app may grow its own again -----------------------------------------

def test_no_app_defines_its_own_redaction():
    """Nineteen apps had their own copy and they drifted into three
    versions, so a fix to one left the rest leaking. There is one copy,
    in core, and this is what keeps it that way."""
    offenders = []
    for site in sorted((REPO / "apps").glob("*/*_site.py")):
        text = site.read_text(encoding="utf-8", errors="ignore")
        for name in ("redact", "set_private_words"):
            if re.search(r"^def %s\(" % name, text, re.M):
                offenders.append("%s defines %s()" % (site.parent.name, name))
    assert not offenders, (
        "redaction belongs in paperpull_core.redact, not in an app: "
        + ", ".join(offenders))


def test_every_app_that_redacts_imports_it_from_core():
    missing = []
    for site in sorted((REPO / "apps").glob("*/*_site.py")):
        text = site.read_text(encoding="utf-8", errors="ignore")
        # redact_label is a different, app-specific thing and is not this.
        uses = re.search(r"(?<!_)\bredact\(", text) or re.search(r"\bset_private_words\(", text)
        if uses and "from paperpull_core.redact import" not in text:
            missing.append(site.parent.name)
    assert not missing, "uses redaction without importing core's: " + ", ".join(missing)
