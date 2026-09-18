"""Which years a run cares about, so discovery can skip the rest.

Several providers keep statements under a year picker, and selecting a year
costs a round trip, three seconds or so on U.S. Bank. Discovery used to walk
every year and let the scope flags (--year, --start-date, --end-date, and
default_start_date in the config) filter the result afterwards. That is
exhaustive, which is what keeps discovery.json complete for the status
tracker, but it makes a scoped run wait on years it will throw away.

The rule here is the one that keeps both properties. A scoped run skips
FETCHING years outside its window. It never forgets what earlier runs
found, because discovery only ever adds to discovery.json. An unscoped run
still walks everything, so the status tracker's gap detection is fed by the
runs people actually do most.

A picker option that names no year at all ("Current", "Last 12 months",
"All") is always kept. One that names a year and a direction ("2020 and
earlier", "Before 2019") is kept when any year it covers is inside the
window.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, List, Optional, Tuple

_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_OLDER = re.compile(r"\b(and\s+)?(earlier|older|before|prior|previous)\b", re.I)
_NEWER = re.compile(r"\b(and\s+)?(later|newer|after|onwards?)\b", re.I)


def year_window(args, config: Optional[dict] = None) -> Tuple[Optional[int], Optional[int]]:
    """(first, last) year the run cares about, either end None for open.
    --year wins. Otherwise --start-date, then default_start_date from the
    config, sets the first, and --end-date sets the last."""
    year = getattr(args, "year", None)
    if year:
        return int(year), int(year)
    start = getattr(args, "start_date", None) or (config or {}).get("default_start_date")
    end = getattr(args, "end_date", None)
    first = int(str(start)[:4]) if start and str(start)[:4].isdigit() else None
    last = int(str(end)[:4]) if end and str(end)[:4].isdigit() else None
    return first, last


def in_window(label: str, window: Tuple[Optional[int], Optional[int]]) -> bool:
    """Whether a picker option could hold anything the run wants."""
    first, last = window
    if first is None and last is None:
        return True
    years = [int(y) for y in _YEAR.findall(label or "")]
    if not years:
        return True
    lo, hi = min(years), max(years)
    if _OLDER.search(label or ""):
        lo = None
    if _NEWER.search(label or ""):
        hi = None
    if first is not None and hi is not None and hi < first:
        return False
    if last is not None and lo is not None and lo > last:
        return False
    return True


def period_filter(args, config: Optional[dict] = None) -> Optional[Callable[[str], bool]]:
    """A predicate for picker options, or None when the run is unscoped so a
    caller can tell the difference between 'keep all' and 'keep these'."""
    window = year_window(args, config)
    if window == (None, None):
        return None
    return lambda label: in_window(label, window)


def periods_in_scope(options: Iterable[str], args, config: Optional[dict] = None) -> List[str]:
    keep = period_filter(args, config)
    options = list(options)
    if keep is None:
        return options
    return [o for o in options if keep(o)]


def describe(window: Tuple[Optional[int], Optional[int]]) -> str:
    first, last = window
    if first is not None and last is not None:
        return str(first) if first == last else "%d to %d" % (first, last)
    if first is not None:
        return "%d onward" % first
    if last is not None:
        return "up to %d" % last
    return "every year"
