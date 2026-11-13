"""A list read again after a refused document, as paperpull_core.refused
reads it, on its own, so each of its three answers can be seen apart from
any provider. Each app's own tests drive its handler through it, and
test_every_app_weighs_a_refused_document_against_its_list.py holds every
app that weighs a refusal to reading its list this way.
"""
import pytest

from paperpull_core.refused import list_again


class SignedOut(Exception):
    pass


class ListStopped(Exception):
    pass


class OtherAccount(Exception):
    pass


class NotSignedOut(SignedOut):
    """A sign-out of a kind of its own, built on the app's one."""


def _again(read, stops=()):
    return list_again(read, SignedOut, ListStopped, stops)


def _raises(e):
    def read():
        raise e
    return read


def test_a_list_with_something_in_it_is_read():
    rows = [{"id": "a"}]
    assert _again(lambda: rows) is rows


def test_a_list_built_on_list_is_a_list():
    class Rows(list):
        pass
    rows = Rows([1])
    assert _again(lambda: rows) is rows


@pytest.mark.parametrize("cls", [SignedOut, NotSignedOut])
def test_a_list_refused_too_is_a_sign_out(cls):
    with pytest.raises(cls):
        _again(_raises(cls("refused")))


def test_the_apps_own_list_stop_passes_on_as_it_is():
    stop = ListStopped("the reader's own words")
    with pytest.raises(ListStopped) as got:
        _again(_raises(stop))
    assert got.value is stop


def test_another_stop_of_the_app_passes_on_as_it_is():
    stop = OtherAccount("1234")
    with pytest.raises(OtherAccount) as got:
        _again(_raises(stop), stops=(OtherAccount,))
    assert got.value is stop


@pytest.mark.parametrize("e", [
    RuntimeError("the provider answered 500 for /api/list?account=1234"),
    TimeoutError("Timeout 30000ms exceeded"),
    ConnectionError("net::ERR_CONNECTION_RESET"),
    KeyError("data"),
    ValueError("Expecting value"),
    OtherAccount("1234"),
], ids=["500", "timeout", "network", "missing-field", "not-json", "a-stop-not-named"])
def test_a_list_that_did_not_answer_is_unread_not_a_sign_out(e):
    with pytest.raises(ListStopped) as got:
        _again(_raises(e))
    # Its own words name the kind of failure and nothing the provider said.
    said = str(got.value)
    assert type(e).__name__ in said
    assert "1234" not in said and "api" not in said and "ERR_" not in said
    assert got.value.__cause__ is None and got.value.__suppress_context__


@pytest.mark.parametrize("answer", [None, {}, {"data": [1]}, "rows", (1, 2)],
                         ids=["none", "empty-object", "object", "text", "tuple"])
def test_an_answer_that_is_not_a_list_is_unread(answer):
    with pytest.raises(ListStopped, match="did not answer as a list"):
        _again(lambda: answer)


def test_an_empty_list_is_unread_not_a_sign_out():
    with pytest.raises(ListStopped, match="held nothing"):
        _again(lambda: [])


def test_a_stop_of_the_run_is_never_caught():
    class Stop(SystemExit):
        pass
    with pytest.raises(Stop):
        _again(_raises(Stop(0)))
    with pytest.raises(KeyboardInterrupt):
        _again(_raises(KeyboardInterrupt()))
