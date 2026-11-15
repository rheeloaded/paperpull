"""Which countries a provider is for, and how that is said.

Every app names its countries in its AppSpec, and the panel's provider
list, PROVIDERS.md, the README and the website all say them the one way
label() does, so a provider of one country is never taken for another of
the same name elsewhere (Amazon Visa is a German card here, where the US
one is Chase's).

The panel and the website read an app's storage.py without running it,
so declared() reads the literal values from its source. A census holds
that reading to the imported spec for every app.
"""
import ast
import re
from typing import Dict, Optional, Tuple

# ISO 3166 codes and the names a person reads. A provider in a country
# not here needs its name added first.
NAMES = {
    "AU": "Australia",
    "BE": "Belgium",
    "CA": "Canada",
    "DE": "Germany",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "IT": "Italy",
    "MX": "Mexico",
    "NL": "Netherlands",
    "PL": "Poland",
    "SE": "Sweden",
    "US": "United States",
}
# Names that take "the" inside a sentence.
_THE = {"GB", "NL", "US"}


def name(code: str) -> str:
    """The country's name, or the code itself when it is not one known."""
    return NAMES.get(code, code)


def in_sentence(code: str) -> str:
    """"the United States", "Germany"."""
    return ("the " if code in _THE else "") + name(code)


def label(countries, may_work_elsewhere: bool = False) -> str:
    """The few words a list shows under a provider's name. "Germany" for
    one country, "14 countries" for several, and for a service with one
    site worldwide that was built on an account in one country,
    "United States, may work elsewhere". "" when none is declared."""
    countries = tuple(countries or ())
    if not countries:
        return ""
    if len(countries) > 1:
        return "%d countries" % len(countries)
    if may_work_elsewhere:
        return "%s, may work elsewhere" % name(countries[0])
    return name(countries[0])


def store_label(site: str, code: str) -> str:
    """"amazon.de (Germany)", how a store is offered in a list."""
    return "%s (%s)" % (site, name(code))


def store_site(value) -> str:
    """A store as a config may name it, "https://www.Amazon.de/" say, read
    as the app reads it (amazon_site.set_marketplace), "amazon.de". "" for
    anything that is not a string."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"^(https?://)?(www\.)?", "", value.strip().lower()).rstrip("/")


def check(countries, may_work_elsewhere=False, stores=None, store_setting=None) -> None:
    """ValueError when the declaration cannot be right, called by AppSpec.
    An app may still declare none, which the census refuses for every app
    PaperPull ships."""
    countries = tuple(countries or ())
    stores = dict(stores or {})
    unknown = [c for c in countries if c not in NAMES]
    if unknown:
        raise ValueError("AppSpec.countries has %s, which countries.NAMES does not name"
                         % ", ".join(map(repr, unknown)))
    if len(set(countries)) != len(countries):
        raise ValueError("AppSpec.countries names a country twice")
    if may_work_elsewhere and len(countries) != 1:
        raise ValueError("AppSpec.may_work_elsewhere is for a provider of one country")
    if bool(stores) != bool(store_setting):
        raise ValueError("AppSpec.stores and AppSpec.store_setting come together")
    if stores and set(stores.values()) != set(countries):
        raise ValueError("AppSpec.stores' countries must be AppSpec.countries")


def declared(source: str) -> Dict[str, object]:
    """The countries, may_work_elsewhere, stores and store_setting an app's
    storage.py gives its AppSpec, read from the source without running it.
    A value that is not a plain literal there is left out, as is the whole
    reading when the source does not parse."""
    out: Dict[str, object] = {"countries": (), "may_work_elsewhere": False,
                              "stores": {}, "store_setting": None}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _called(node) == "AppSpec"):
            continue
        for kw in node.keywords:
            if kw.arg not in out:
                continue
            try:
                value = ast.literal_eval(kw.value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue
            if kw.arg == "countries" and isinstance(value, (tuple, list)) \
                    and all(isinstance(c, str) for c in value):
                out["countries"] = tuple(value)
            elif kw.arg == "may_work_elsewhere" and isinstance(value, bool):
                out["may_work_elsewhere"] = value
            elif kw.arg == "stores" and isinstance(value, dict) \
                    and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                out["stores"] = dict(value)
            elif kw.arg == "store_setting" and isinstance(value, str):
                out["store_setting"] = value
        break
    return out


def _called(node: ast.Call) -> Optional[str]:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def offered(countries: Tuple[str, ...], may_work_elsewhere: bool = False) -> dict:
    """What a list is handed for one provider, its codes, their names and
    its label."""
    countries = tuple(countries or ())
    return {"countries": list(countries), "country_names": [name(c) for c in countries],
            "country_label": label(countries, may_work_elsewhere),
            "may_work_elsewhere": bool(may_work_elsewhere)}
