"""A page whose password fields cannot be counted is never read as signed in."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marinwater_site as site


class _Page:
    url = "https://ipn4.paymentus.com/cp/landing.action"

    def locator(self, selector):
        raise RuntimeError("invented, the page went away")


def test_a_page_whose_fields_cannot_be_counted_is_signed_out():
    assert site.looks_signed_out(_Page())


def test_only_drawn_password_fields_count_as_the_core_reads_them():
    from paperpull_core import recorder
    assert site.PASSWORD_FIELD == recorder.DRAWN_PASSWORD_FIELD
