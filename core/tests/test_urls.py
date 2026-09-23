"""The one URL guard, with the cases the forty-eight copies disagreed on.

Each of these was true in some apps and false in others before the logic
moved here, which is the reason it moved.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.urls import is_safe_url  # noqa: E402

HOSTS = {"chase.com"}


# -- what must be allowed ------------------------------------------------------

def test_the_host_itself():
    assert is_safe_url("https://chase.com/statements", HOSTS)


def test_a_subdomain_by_default():
    assert is_safe_url("https://secure.chase.com/x", HOSTS)
    assert is_safe_url("https://a.b.chase.com/x", HOSTS)


def test_the_explicit_port_443():
    assert is_safe_url("https://chase.com:443/x", HOSTS)


def test_a_trailing_dot_is_the_same_host():
    """The DNS root. Half the apps stripped it and half refused it."""
    assert is_safe_url("https://chase.com./x", HOSTS)
    assert is_safe_url("https://secure.chase.com./x", HOSTS)


def test_the_case_of_the_host_does_not_matter():
    assert is_safe_url("https://SECURE.Chase.COM/x", HOSTS)


def test_an_allowlist_written_untidily_still_works():
    assert is_safe_url("https://chase.com/x", {" Chase.COM. "})


# -- what must be refused ------------------------------------------------------

def test_another_host_entirely():
    assert not is_safe_url("https://evil.example/x", HOSTS)


def test_a_host_that_merely_ends_in_the_same_letters():
    """The reason matching is by label and never by string prefix."""
    assert not is_safe_url("https://notchase.com/x", HOSTS)
    assert not is_safe_url("https://chase.com.evil.example/x", HOSTS)


def test_plain_http():
    assert not is_safe_url("http://chase.com/x", HOSTS)


def test_a_scheme_that_is_not_the_web_at_all():
    for url in ("file:///c:/secrets.txt", "javascript:alert(1)",
                "data:text/html,<b>x</b>", "ftp://chase.com/x"):
        assert not is_safe_url(url, HOSTS), url


def test_credentials_in_the_address():
    """`https://chase.com@evil.example/` has a host of evil.example, and
    reads to a person as though it were Chase."""
    assert not is_safe_url("https://chase.com@evil.example/x", HOSTS)
    assert not is_safe_url("https://user:pw@chase.com/x", HOSTS)


def test_any_other_port():
    assert not is_safe_url("https://chase.com:8443/x", HOSTS)


def test_a_port_that_is_not_a_number_at_all():
    """Reading .port raises instead of answering, which used to come back
    as a traceback rather than as a refusal."""
    assert not is_safe_url("https://chase.com:99999/x", HOSTS)
    assert not is_safe_url("https://chase.com:notaport/x", HOSTS)


def test_nothing_useful_at_all():
    for url in ("", None, "   ", "https://", "not a url"):
        assert not is_safe_url(url, HOSTS), url


def test_an_empty_allowlist_matches_nothing():
    assert not is_safe_url("https://chase.com/x", set())
    assert not is_safe_url("https://chase.com/x", {"", "  "})


# -- the six apps that must not follow subdomains ------------------------------

def test_subdomains_off_takes_the_host_and_nothing_under_it():
    assert is_safe_url("https://chase.com/x", HOSTS, subdomains=False)
    assert not is_safe_url("https://secure.chase.com/x", HOSTS, subdomains=False)


def test_subdomains_off_still_refuses_everything_else():
    for url in ("http://chase.com/x", "https://chase.com:8443/x",
                "https://chase.com@evil.example/x", "https://notchase.com/x"):
        assert not is_safe_url(url, HOSTS, subdomains=False), url


def test_subdomains_off_lists_the_subdomains_it_wants():
    """How an exact-match app allows one, by naming it."""
    hosts = {"chase.com", "secure.chase.com"}
    assert is_safe_url("https://secure.chase.com/x", hosts, subdomains=False)
    assert not is_safe_url("https://other.chase.com/x", hosts, subdomains=False)
