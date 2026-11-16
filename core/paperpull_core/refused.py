"""A provider's list, read again after it refused one document.

A provider that refuses one document, with a 401, a 403, a redirect or a
page where the file should be, may have ended the session or may be
refusing that one document. So the app reads its list again with the call
that proves a session (core/tests/test_every_app_weighs_a_refused_
document_against_its_list.py), and that reading has three answers, which
are kept apart.

- Signed out. The list is refused too, by the same kind of answer. The
  app's own sign-out passes on and stops the run as signed out.
- Unread. The list did not answer (a 500, a timeout, a network error),
  answered with something that is not its list, or held nothing, though
  it listed the refused document before. None of those says the session
  ended, and none says it still holds. So the run stops with the list
  unread (listing.read_again_stopped), nothing is recorded against the
  document, and a run that lists first takes it again.
- Read. The list came back with something in it. The refusal was that
  document's own, which fails alone, and the run goes on.

When sixteen more apps were first made to weigh a refusal against the list
(2026-11-13), an independent review found an unread list read one of two
wrong ways. A list that answered 500 or timed out reached the loop as one
document's failure, so the run went on with no session shown (Affirm), and
a list that held nothing, or never came, was read as a sign-out, which
nothing in it said (Affirm, FedEx, myPay, Stripe, UPS). list_again() is the
one way an app reads its list again after a refusal, so the three stay
apart in every app, and the census above holds each app to it. Cetera, NW
Natural and Portland General Electric read their list through it too when
they hold none from this run, or the one they hold lacks the document,
since that document was listed before, so a list that does not answer
there says the same. Its words say only that the list was read again.
"""
from __future__ import annotations

from typing import Callable, Iterable, Type


def list_again(read: Callable[[], list], signed_out: Type[BaseException],
               unread: Type[BaseException], stops: Iterable[Type[BaseException]] = ()) -> list:
    """The list `read()` gives, read again after one document was refused,
    when it gives a list with something in it.

    `signed_out` is the app's sign-out, raised by `read` for a list refused
    too, and `stops` are the app's other stops a list read can raise (an
    account the page does not show, a check for the person). Each passes on
    as it is, and so does `unread` itself, raised by a reader that knows
    why its list stopped. Any other exception, and an answer that is not a
    list or is an empty one, raises `unread` with this module's own words,
    which name the kind of exception and nothing it said, since its words
    may hold the provider's."""
    keep = (signed_out, unread) + tuple(stops)
    try:
        got = read()
    except keep:
        raise
    except Exception as e:
        raise unread("the list did not answer when it was read again (%s)"
                     % type(e).__name__) from None
    if not isinstance(got, list):
        raise unread("the list read again did not answer as a list")
    if not got:
        raise unread("the list read again held nothing")
    return got
