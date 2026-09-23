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
