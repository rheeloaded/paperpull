"""The one URL guard, with the cases the forty-eight copies disagreed on.

Each of these was true in some apps and false in others before the logic
moved here, which is the reason it moved.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.urls import host_matches, host_of, is_safe_url, join  # noqa: E402

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


# -- a host Python and a browser read differently ------------------------------

# urlsplit ends the host at the first /, ? or #, and a browser (Chromium,
# Node, Playwright's own request client) also at a backslash. So each of
# these has a Python host ending in .chase.com and a browser host of
# evil.example. Measured with Node's URL, which follows the same standard,
# "https://evil.example\\.chase.com/x" reads as host evil.example, path
# /.chase.com/x.
BACKSLASHED = [
    "https://evil.example\\.chase.com/x",
    "https://evil.example\\.chase.com",
    "https://evil.example\\.secure.chase.com/statement.pdf",
    "https://evil.example\\.chase.com./x",
    "https://EVIL.example\\.Chase.COM/x",
    "https://evil.example\\\\.chase.com/x",
    "https://evil.example\\/.chase.com/x",
]


def test_a_backslash_in_the_host_is_never_the_provider():
    for url in BACKSLASHED:
        assert not is_safe_url(url, HOSTS), url
        assert not is_safe_url(url, HOSTS | {"secure.chase.com"}, subdomains=False), url


def test_any_host_that_is_not_a_plain_name_is_refused():
    """Fail closed. A browser decodes, maps or refuses each of these, and
    which one it does is not this guard's to guess."""
    for url in ("https://evil.example%5C.chase.com/x",
                "https://evil.example%2F.chase.com/x",
                "https://evil.example%2e.chase.com/x",
                "https://evil.example .chase.com/x",
                "https://evil.example／.chase.com/x",
                "https://evil.example＼.chase.com/x",
                "https://chаse.com/x"):
        assert not is_safe_url(url, HOSTS), url


def test_a_plain_name_still_passes_in_every_form_it_did():
    for url in ("https://chase.com/x", "https://secure.chase.com/x",
                "https://a-b.chase.com/x", "https://a_b.chase.com/x",
                "https://s3.chase.com/x", "https://SECURE.Chase.COM./x",
                "https://chase.com:443/x"):
        assert is_safe_url(url, HOSTS), url


def test_host_of_gives_a_plain_name_or_nothing():
    assert host_of("https://Secure.Chase.com./x") == "secure.chase.com"
    assert host_of("http://chase.com:8080/x") == "chase.com"
    for url in BACKSLASHED + ["", None, "not a url", "https://"]:
        assert host_of(url) == "", url


# A backslash before the host's own @, so urlsplit takes what comes before it
# for a user and reads the host as chase.com, while a browser ends the host
# at the backslash and reads evil.example.
IN_THE_USER = [
    "https://evil.example\\@chase.com/x",
    "https://evil.example\\@secure.chase.com/x",
    "https://evil.example\\:pw@chase.com/x",
]

# A backslash after the host, which a browser reads as a slash. Requested as
# it is, this one stays on Chase, but checked and then left to a browser to
# resolve as a link, `/\evil.example/x` goes to evil.example.
IN_THE_PATH = [
    "https://chase.com/\\evil.example/x",
    "https://chase.com\\/evil.example/x",
]


def test_a_backslash_anywhere_before_the_query_is_refused():
    for url in IN_THE_USER + IN_THE_PATH:
        assert not is_safe_url(url, HOSTS), url
        assert host_of(url) == "", url


def test_a_backslash_in_the_query_or_fragment_is_only_text():
    assert is_safe_url("https://chase.com/x?path=a\\b", HOSTS)
    assert is_safe_url("https://chase.com/x#a\\b", HOSTS)
    assert host_of("https://chase.com/x?path=a\\b") == "chase.com"


def test_a_host_is_not_tidied_into_a_plain_name():
    """A browser keeps these, and asks no host of Chase's. Tidying them
    first answered for an address no browser would go to."""
    for url in ("https://chase.com　/x", "https:// chase.com/x",
                "https://chase.com\x1f/x", "https://chase.com../x",
                "https://chase.com.../x", "https://chase.com /x"):
        assert not is_safe_url(url, HOSTS), repr(url)
        assert host_of(url) == "", repr(url)
    assert not host_matches(" chase.com", HOSTS)
    assert not host_matches("chase.com..", HOSTS)


# -- join, a link as a browser resolves it -------------------------------------

PAGE = "https://secure.chase.com/statements/list?x=1"


def test_join_resolves_an_ordinary_link_as_urljoin_does():
    for href, want in [
        ("/statements/2031.pdf", "https://secure.chase.com/statements/2031.pdf"),
        ("2031.pdf", "https://secure.chase.com/statements/2031.pdf"),
        ("?page=2", "https://secure.chase.com/statements/list?page=2"),
        ("https://secure.chase.com/a?b=c\\d", "https://secure.chase.com/a?b=c\\d"),
        ("//static.chase.com/a.pdf", "https://static.chase.com/a.pdf"),
        ("https:/a.pdf", "https://secure.chase.com/a.pdf"),
        ("https:a.pdf", "https://secure.chase.com/statements/a.pdf"),
        ("  /a.pdf\n", "https://secure.chase.com/a.pdf"),
        ("/a\t.pdf", "https://secure.chase.com/a.pdf"),
        ("//evil.example/x", "https://evil.example/x"),
    ]:
        assert join(PAGE, href) == want, href


# Each of these resolves to Chase by urljoin and to evil.example in a
# browser. Measured with Node's URL, which follows the same standard.
TO_ANOTHER_HOST = [
    "/\\evil.example/x",
    "\\\\evil.example/x",
    "\\/evil.example/x",
    "///evil.example/x",
    "////evil.example/x",
    "https:///evil.example/x",
    "HTTPS:////evil.example/x",
    "/\t//evil.example/x",
    "http:evil.example/x",
    "http:/evil.example/x",
]


def test_join_gives_nothing_for_a_link_a_browser_resolves_elsewhere():
    from urllib.parse import urljoin
    for href in TO_ANOTHER_HOST:
        assert join(PAGE, href) == "", href
        assert not is_safe_url(join(PAGE, href), HOSTS), href
    # What urljoin made of the first ones, and the guard took for Chase's.
    assert is_safe_url(urljoin(PAGE, "///evil.example/x"), HOSTS)
    assert is_safe_url(urljoin(PAGE, "https:///evil.example/x"), HOSTS)


def test_host_matches_by_label_and_only_for_a_plain_name():
    assert host_matches("chase.com", HOSTS)
    assert host_matches("secure.chase.com", HOSTS)
    assert host_matches("Secure.Chase.com.", HOSTS)
    assert not host_matches("secure.chase.com", HOSTS, subdomains=False)
    assert not host_matches("notchase.com", HOSTS)
    assert not host_matches("evil.example\\.chase.com", HOSTS)
    assert not host_matches("", HOSTS)
    assert not host_matches(None, HOSTS)
    assert not host_matches("chase.com", set())
