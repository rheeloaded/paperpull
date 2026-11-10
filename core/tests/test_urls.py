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


# -- where a refused address leads ---------------------------------------------

def test_a_refusal_says_where_the_address_leads_and_nothing_an_account_is_in():
    from paperpull_core.urls import where_it_leads
    assert where_it_leads("https://evil.example/statements/12345?acct=9876#x") == "https://evil.example"
    assert where_it_leads("https://user:secret@evil.example:8443/a") == "https://evil.example:8443"
    assert where_it_leads("HTTP://Evil.Example/a") == "http://evil.example"
    assert where_it_leads("about:blank") == "an address with no host (about:)"
    assert where_it_leads("javascript:alert(1)") == "an address with no host (javascript:)"
    assert where_it_leads("/statements/12345") == "an address with no scheme"
    assert where_it_leads("") == "an address with no scheme"
    assert where_it_leads(None) == "an address with no scheme"
    assert where_it_leads("https://[::1") == "an address that could not be read"
    for said in (where_it_leads("https://user:secret@evil.example/12345?acct=9876"),):
        assert "secret" not in said and "12345" not in said and "9876" not in said


def test_a_host_that_carries_words_an_id_or_a_token_leaves_as_its_shape():
    """A host is read from the page too. One that is no host name but a
    page's words, or one whose label reads like an account's number or a
    token, leaves as its shape, every letter as a and every digit as 9, and
    a plain host name as it is."""
    from paperpull_core.urls import where_it_leads
    said = where_it_leads("https://Statement for Zorvex 0400/x")
    assert said == "https://aaaaaaaaa_aaa_aaaaaa_9999"
    assert where_it_leads("https://acct-123456789.example/x") == "https://aaaa-999999999.example"
    assert where_it_leads("https://d3fgh8kl2mn4op.cloudfront.example/x") == "https://a9aaa9aa9aa9aa.cloudfront.example"
    assert where_it_leads("https://jo.doe%40mail.example/x") == "https://aa.aaa_99aaaa.aaaaaaa"
    assert where_it_leads("https://secure07a.chase.com./x") == "https://secure07a.chase.com"
    assert where_it_leads("https://s3-us-west-2.amazonaws.com/b") == "https://s3-us-west-2.amazonaws.com"
    assert where_it_leads("https://[2001:db8::1]:8443/x") == "https://[2001:db8::1]:8443"
    assert where_it_leads("https://[fe80::1%25Zorvex]/x") == "https://[fe80::1]"
    assert where_it_leads("https://203.0.113.5/x") == "https://203.0.113.5"


def test_naming_where_an_address_leads_never_asks_anything_of_it(monkeypatch):
    import socket
    from paperpull_core.urls import where_it_leads

    def asked(*a, **k):
        raise AssertionError("the address was asked for")

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, asked)
    assert where_it_leads("https://elsewhere.example/statement.pdf") == "https://elsewhere.example"
    assert where_it_leads("https://xn--bnk-sna.example/") == "https://xn--bnk-sna.example"
