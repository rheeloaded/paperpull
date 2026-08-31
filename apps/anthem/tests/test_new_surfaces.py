"""ID cards, Letters, and prior-year member documents - the three surfaces added
after the EOB collector. All data here is SYNTHETIC (JANE DOE, made-up coverage
keys). These cover the pure filing logic and the read-only safety contracts;
the browser-facing fetch is validated by the live pilot.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import anthem_site as site
from storage import build_pdf_filename

SRC = (Path(__file__).resolve().parents[1] / "anthem_site.py").read_text(encoding="utf-8")

# Synthetic coverage-period ids (source-code - dates - plan - group), never real.
KEY_2026H2 = "79CB-20260701-20261231-MED-000000A00A"
KEY_2026H1 = "79DM-20260101-20260701-MED-000000A00A"
KEY_2025 = "79DM-20250101-20251231-MED-000000A00A"
KEY_2024 = "79DM-20240701-20241231-MED-000000A00A"


# -- coverage period parsing -------------------------------------------------

def test_a_coverage_period_id_yields_its_start_date_and_label():
    assert site.period_start(KEY_2026H2) == "2026-07-01"
    assert site.period_start(KEY_2025) == "2025-01-01"
    assert site.period_label(KEY_2026H2) == "2026 H2"
    assert site.period_label(KEY_2026H1) == "2026 H1"
    assert site.period_label(KEY_2025) == "2025 H1"


def test_a_coverage_period_id_is_validated_to_its_known_shape():
    assert site.valid_coverage_key(KEY_2025)
    for bad in ["", "not-a-key", "79DM-2025-2025-MED-x",
                "../etc/passwd", "79DM-20250101-20251231-MED-x;rm",
                "https://evil.test/79DM-20250101-20251231-MED-000000A00A"]:
        assert not site.valid_coverage_key(bad), bad


# -- the period-aware identity fixes the cross-year collision ----------------

def test_a_prior_year_document_does_not_collide_with_its_current_year_namesake():
    """The member-document dedupe key includes the coverage period, so a 2025
    "Evidence of Coverage" and the 2026 one are distinct identities and distinct
    delete-safe keys - neither dedupes the other away, and their filenames differ
    once the period label rides into the name."""
    id_2025 = site.member_doc_id(KEY_2025, "EOC")
    id_2026 = site.member_doc_id(KEY_2026H2, "EOC")
    assert id_2025 != id_2026
    assert site.member_doc_key(KEY_2025, "EOC") != site.member_doc_key(KEY_2026H2, "EOC")
    storage.set_filename_owner("")
    label_2025 = f"{site.document_label_for('EOC')} ({site.period_label(KEY_2025)})"
    label_2026 = f"{site.document_label_for('EOC')} ({site.period_label(KEY_2026H2)})"
    f25 = build_pdf_filename(site.period_start(KEY_2025), label_2025, "")
    f26 = build_pdf_filename(site.period_start(KEY_2026H2), label_2026, "")
    assert f25 != f26
    assert "2025" in f25 and "2026" in f26


def test_document_type_codes_become_readable_labels():
    assert site.document_label_for("EOC") == "Evidence of Coverage"
    assert site.document_label_for("COCC") == "Certificate of Coverage"
    assert site.document_label_for("PPOCONF") == "Plan Confirmation"
    # an unknown code still files sensibly under its own code
    assert site.document_label_for("XYZZY") == "XYZZY"


def test_member_documents_route_to_the_right_folder():
    assert site.document_folder_for("EOC Evidence of Coverage") == "plan_documents"
    assert site.document_folder_for("PPOCONF Plan Confirmation") == "plan_documents"
    assert site.document_folder_for("1095-B Health Coverage") == "tax_documents"
    assert site.document_folder_for("Prior Authorization Approval") == "authorizations"


def test_the_download_url_uses_fixed_constants_and_the_right_download_id():
    """The download is built from a validated coverage key, the constant
    documentTypeCd=All and origin=planDocument (both confirmed to serve every
    document type live), and a downloadId taken from the row's uuid for a
    uuid-typed document else its type code."""
    assert site._DOC_ORIGIN == "planDocument"
    assert site._DOC_TYPE_CD == "All"
    # the in-page builder chooses uuid vs type code by downloadIdType
    assert "row.downloadIdType === 'uuid'" in SRC
    assert "row.uuid" in SRC and "row.documentType" in SRC


# -- ID cards ----------------------------------------------------------------

def test_id_card_list_yields_one_row_per_member_and_card():
    """listIdCard returns patient[] each with healthIdentificationCard[]; the
    parser yields one filing row per (member, card), the name tidied for the
    filename and the opaque card identifier NOT carried (resolved fresh)."""
    body = {"result": {"data": {"patient": [
        {"name": {"given": ["JANE"], "family": "DOE"},
         "birthDate": "2010-01-01", "subscriber": False,
         "healthIdentificationCard": [
             {"identifier": [{"type": "idCardId", "value": "opaque-A"}],
              "cardType": "normal", "effectiveDate": "2026-01-01"}]},
        {"name": {"given": ["JOHN"], "family": "DOE"},
         "birthDate": "1980-01-01", "subscriber": True,
         "healthIdentificationCard": [
             {"identifier": [{"type": "idCardId", "value": "opaque-B"}],
              "cardType": "normal", "effectiveDate": "2026-01-01"}]},
    ]}}}
    cards = site.parse_id_card_list(body)
    assert len(cards) == 2
    assert cards[0]["patient"] == "Jane Doe"   # all-caps tidied
    assert cards[1]["patient"] == "John Doe"
    assert cards[0]["card_type"] == "normal"
    assert cards[0]["date"] == "2026-01-01"
    # the opaque card identifier is never carried in the row
    for c in cards:
        for v in c.values():
            assert "opaque" not in str(v)


def test_id_card_keys_keep_each_members_card_distinct():
    a = site.idcard_key("Jane Doe:0", "normal")
    b = site.idcard_key("John Doe:0", "normal")
    assert a != b
    storage.set_filename_owner("")
    fa = build_pdf_filename("2026-01-01", "Jane Doe Insurance Card", "")
    fb = build_pdf_filename("2026-01-01", "John Doe Insurance Card", "")
    assert fa != fb


def test_the_id_card_identifier_is_resolved_fresh_never_stored():
    """Like the EOB eobId, the opaque card identifier is a session token: the
    view call resolves it from a current listing at download time rather than
    trusting a stored value."""
    assert "def download_id_card" in SRC
    assert "idcard.v1.listIdCard" in SRC  # re-listed at download to resolve the id
    assert "idcard.v1.viewIdCard" in SRC


# -- Letters (READ-SAFE) -----------------------------------------------------

def test_letters_parse_to_filing_rows_with_a_calendar_date():
    msgs = [
        {"msgUid": "u-1", "subject": "Your claim was processed",
         "body": "<p>Details here</p>", "createDtTime": 1767225600000,
         "isRead": False, "replyEnabled": True},
        {"msgUid": "u-2", "subject": "  Plan update  ",
         "body": "plain text\nsecond line", "createDtTime": 1767225600000,
         "isRead": True},
    ]
    rows = site.parse_letters(msgs)
    assert len(rows) == 2
    assert rows[0]["msg_uid"] == "u-1"
    assert rows[0]["label"] == "Your claim was processed"   # trimmed
    assert rows[1]["label"] == "Plan update"                 # whitespace collapsed
    assert rows[0]["is_read"] is False and rows[1]["is_read"] is True
    # epoch millis -> a real calendar date
    assert rows[0]["date"].startswith("20")
    # a message with no id is dropped, not guessed
    assert site.parse_letters([{"subject": "x", "body": "y"}]) == []


def test_reading_letters_never_marks_them_read():
    """The message list already carries every body, so no message is ever opened,
    and the app never calls a mark-read/open action. Fetching letters cannot
    change a read flag in the portal."""
    # the collector only GETs the messages list; there is no open/mark-read POST
    assert "securemessage" in SRC
    for mutating in ("markRead", "markAsRead", "setRead", "readReceipt",
                     "method: 'POST'", 'method:"POST"', "method: 'PUT'"):
        assert mutating not in SRC, mutating
    # is_read is only ever READ off the message, never written back
    assert 'm.get("isRead")' in SRC


def test_letter_keys_are_per_message():
    assert site.letter_key("u-1") != site.letter_key("u-2")
    assert site.letter_key("../etc") == "letter:.._etc"


# -- auth: every surface's bearer stays in the page --------------------------

def test_every_surface_bearer_is_captured_in_page_not_lifted_into_python():
    """Each surface reads its bearer from an in-page window bucket; none is pulled
    into this process. The per-microapp buckets (eob, idcard) and the shared
    membersecure bucket all live on window.__hdrs, and the compat window.__eobHeaders
    keeps the untouched EOB path working."""
    assert "window.__hdrs" in SRC
    assert "window.__eobHeaders" in SRC   # EOB compat mirror, untouched path
    assert "window.__hdrs && window.__hdrs.idcard" in SRC
    assert "window.__hdrs && window.__hdrs.ms" in SRC
    # Python never reads an auth header off a request - that would lift the token.
    for py_leak in ("all_headers()", "request.headers", ".get('authorization'",
                    '.get("authorization"'):
        assert py_leak not in SRC, py_leak


def test_the_new_navigations_only_target_host_checked_urls():
    """The prime navigations (to the documents and ID-card pages) are built from
    this app's own URLS and guarded by is_safe_url - never a stored value."""
    assert 'URLS["member_documents"] = DOCUMENTS_URL' in SRC
    assert 'URLS["idcard"] = IDCARD_URL' in SRC
    assert "if not is_safe_url(target)" in SRC
    assert site.is_safe_url(site.DOCUMENTS_URL)
    assert site.is_safe_url(site.IDCARD_URL)


def test_a_letter_body_cannot_phone_home_when_rendered():
    """A letter body is rendered to PDF with all network blocked, so an embedded
    tracking pixel or remote resource cannot load."""
    assert "def render_html_to_pdf" in SRC
    assert 'r.abort()' in SRC
    assert 'Page.printToPDF' in SRC


# -- robustness: a failed listing must not read as an empty archive ----------

class _FakeMSPage:
    """An Anthem-hosted page, already primed, whose listing evaluate returns a
    canned result - to exercise the fail-loud path without a real browser."""

    def __init__(self, listing):
        self.url = "https://membersecure.anthem.com/member/documents"
        self._listing = listing

    def add_init_script(self, _script):
        pass

    def goto(self, *a, **k):
        pass

    def wait_for_timeout(self, *a, **k):
        pass

    def evaluate(self, js, arg=None):
        # _prime_bucket's readiness probe is the only arrow-function; everything
        # else is the surface's listing script.
        if js.strip().startswith("([b, m])"):
            return True
        return self._listing


def test_a_failed_listing_raises_rather_than_reporting_empty_success():
    """A 429/5xx (or a thrown evaluate) must stop the surface loudly, not return
    an empty list that the run would print as "No documents" and exit 0."""
    import pytest
    for bad in ({"status": 429}, {"status": 503}, {"status": 500}):
        with pytest.raises(site.ListingIncomplete):
            site.list_member_documents(_FakeMSPage(bad))
    # a 200 with no rows is a LEGITIMATE empty, not an error
    assert site.list_member_documents(_FakeMSPage({"status": 200, "rows": []})) == []


def test_a_listing_error_counts_as_a_failure_so_the_run_exits_nonzero():
    docsrc = (Path(__file__).resolve().parents[1] / "anthem_docs.py").read_text(encoding="utf-8")
    assert hasattr(site, "ListingIncomplete")
    assert "except site.ListingIncomplete" in docsrc
    # _listing_incomplete bumps the failed count, and main() returns nonzero when
    # stats["failed"] is set - so an incomplete archive never exits clean.
    assert 'self.stats["failed"] += 1' in docsrc


def test_a_failed_coverage_period_is_reported_by_name_not_dropped():
    """A single coverage period whose document list fails must be surfaced, so a
    whole prior year cannot go missing silently."""
    assert "failedPeriods" in SRC
    assert "could not be" in SRC and "coverage period" in SRC


def test_resume_also_retries_the_member_documents_id_cards_and_letters():
    """A run interrupted after the EOBs must still finish the other surfaces on
    --resume; they are idempotent, so resume re-lists and retries the pending
    ones rather than reporting everything complete."""
    import re as _re
    docsrc = (Path(__file__).resolve().parents[1] / "anthem_docs.py").read_text(encoding="utf-8")
    m = _re.search(r"def cmd_resume\(self\):.*?(?=\n    def )", docsrc, _re.S)
    assert m, "cmd_resume not found"
    body = m.group(0)
    for call in ("self.cmd_documents()", "self.cmd_id_cards()", "self.cmd_letters()"):
        assert call in body, call
