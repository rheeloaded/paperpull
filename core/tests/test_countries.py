"""How a provider's countries are said and read. Every value is invented."""
import pytest

from paperpull_core import countries
from paperpull_core.spec import AppSpec


def test_one_country_is_its_name():
    assert countries.label(("DE",)) == "Germany"
    assert countries.label(("US",)) == "United States"


def test_several_are_counted():
    assert countries.label(("US", "CA", "GB")) == "3 countries"


def test_a_service_of_one_site_worldwide_says_it_may_work_elsewhere():
    assert countries.label(("US",), True) == "United States, may work elsewhere"


def test_none_declared_says_nothing():
    assert countries.label(()) == "" and countries.label(None) == ""


def test_a_store_says_its_country():
    assert countries.store_label("amazon.de", "DE") == "amazon.de (Germany)"


@pytest.mark.parametrize("value", ["amazon.de", "https://www.Amazon.de/", "www.amazon.de",
                                   " AMAZON.DE ", "http://amazon.de"])
def test_a_store_is_read_as_the_app_reads_it(value):
    assert countries.store_site(value) == "amazon.de"


def test_a_store_that_is_not_a_word_is_none():
    assert countries.store_site(None) == "" and countries.store_site(3) == ""


def test_a_country_inside_a_sentence():
    assert countries.in_sentence("US") == "the United States"
    assert countries.in_sentence("DE") == "Germany"


SOURCE = '''
from paperpull_core.spec import AppSpec, DOCUMENT
SPEC = AppSpec(
    provider="Example Bank",
    project_dir=HERE,
    countries=("DE",),
    may_work_elsewhere=False,
    stores={"example.de": "DE"},
    store_setting="site",
)
'''


def test_declared_reads_the_literals():
    assert countries.declared(SOURCE) == {"countries": ("DE",), "may_work_elsewhere": False,
                                          "stores": {"example.de": "DE"},
                                          "store_setting": "site"}


@pytest.mark.parametrize("source", [
    "SPEC = AppSpec(provider='X', countries=COUNTRIES)",
    "SPEC = AppSpec(provider='X', countries=('US', 3))",
    "SPEC = AppSpec(provider='X', countries=('US',) + ('CA',))",
    "this is not python (",
    "",
])
def test_declared_leaves_out_what_is_not_a_plain_literal(source):
    assert countries.declared(source)["countries"] == ()


def test_declared_reads_the_first_appspec_only():
    two = SOURCE + "\nOTHER = AppSpec(provider='Y', countries=('US',))\n"
    assert countries.declared(two)["countries"] == ("DE",)


def spec(**kw):
    return AppSpec(provider="Example", project_dir=".", **kw)


def test_a_spec_refuses_a_country_not_named():
    with pytest.raises(ValueError, match="NAMES"):
        spec(countries=("XX",))


def test_a_spec_refuses_a_country_twice():
    with pytest.raises(ValueError, match="twice"):
        spec(countries=("US", "US"))


def test_may_work_elsewhere_is_for_one_country():
    with pytest.raises(ValueError, match="one country"):
        spec(countries=("US", "CA"), may_work_elsewhere=True)


def test_stores_and_their_setting_come_together():
    with pytest.raises(ValueError, match="together"):
        spec(countries=("DE",), stores={"example.de": "DE"})
    with pytest.raises(ValueError, match="together"):
        spec(countries=("DE",), store_setting="site")


def test_stores_cover_exactly_the_countries():
    with pytest.raises(ValueError, match="countries"):
        spec(countries=("DE", "US"), stores={"example.de": "DE"}, store_setting="site")


def test_a_spec_with_no_countries_still_loads():
    """The census refuses it for every app PaperPull ships, while one being
    built still runs."""
    assert spec().countries == ()
