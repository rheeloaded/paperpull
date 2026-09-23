"""The small date facts every app needs.

A statement is named by the day its period ends, so an app that knows only
a month has to work out the last day of it, and one that writes a human
label has to name the month. Both were written out in twenty-nine and
seventeen apps, identically, along with the tables they read from. A leap
year rule copied twenty-nine times is twenty-nine chances to copy it
wrong, and the next provider would have made it thirty.

Nothing here knows anything about a provider, so nothing here is passed
in. It is only the calendar.
"""
from __future__ import annotations

# Days in each month, ignoring February in a leap year, which last_day
# handles on its own.
DAYS_IN_MONTH = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def last_day(year: int, month: int) -> int:
    """The last day of a month, as a number.

    February is 29 in a year divisible by four, except a century that is
    not divisible by four hundred. 1900 had 28 days in February and 2000
    had 29.
    """
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return DAYS_IN_MONTH[month]


def human_date(iso: str) -> str:
    """`2026-08-31` as `August 31, 2026`, for a title a person reads.

    Anything this cannot read comes back as it arrived, because a label
    that is merely unexpected is better than a run that stops.
    """
    try:
        y, m, d = iso.split("-")
        return "%s %d, %s" % (MONTH_NAMES[int(m) - 1], int(d), y)
    except Exception:
        return iso


def is_real_date(iso: str) -> bool:
    """Whether `YYYY-MM-DD` names a day that exists.

    A date pattern finds four digits, a dash, two digits, a dash and two
    more, which a reference number is also shaped like. Thirty-seven apps
    read `Reference 1234-56-78` as a date and filed a document under it.
    A statement dated 1234-56-78 sorts after everything, never matches the
    month it belongs to, and leaves a gap where it should have been.
    """
    try:
        y, m, d = (int(p) for p in str(iso).split("-"))
    except (TypeError, ValueError):
        return False
    if not (1900 <= y <= 2200 and 1 <= m <= 12):
        return False
    return 1 <= d <= last_day(y, m)


def checked(iso, empty=None):
    """`iso` when it names a day that exists, and `empty` when it does not.

    `empty` is whatever that app already answers with when it finds no
    date, so a date it should never have believed is indistinguishable
    from one it never found.
    """
    return iso if iso and is_real_date(iso) else empty
