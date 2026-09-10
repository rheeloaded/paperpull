"""Anthem BCBS document classification + the READ-ONLY safety guard.

Classification cases reflect the titles this app synthesises from the EOB API
(claim type + "Explanation of Benefits"). The SAFETY cases are not provisional:
the Anthem member portal can change a PCP, enroll in paperless, appeal a claim,
refill a prescription and message care teams, so the guard is the reason this
app is allowed near the account at all. EOBs are Protected Health Information.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import anthem_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_eobs_classify_as_insurance_and_route_to_the_eobs_folder():
    """An EOB is an explanation of health-insurance benefits, so it classifies
    as Insurance Document, which storage routes to the EOBs folder."""
    for title in ["Medical Explanation of Benefits",
                  "Pharmacy Explanation of Benefits",
                  "Chiropractic Explanation of Benefits"]:
        cat, summary, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.INSURANCE, title
        assert summary == "Explanation of Benefits", (title, summary)
    assert storage.SPEC.routes["Insurance Document"] == "eobs"


def test_an_eob_check_is_told_apart_from_the_eob_statement():
    """A claim can carry both an EOB and a reimbursement EOB Check; the check
    must not be filed under the same summary as the statement."""
    cat, summary, _ = doc_types.classify_document(
        "Medical Explanation of Benefits Check", RULES)
    assert cat == doc_types.INSURANCE
    assert summary == "Explanation of Benefits Check"
    # and they must produce different filenames
    storage.set_filename_owner("")
    eob = build_pdf_filename("2026-08-05", "Explanation of Benefits", "")
    chk = build_pdf_filename("2026-08-05", "Explanation of Benefits Check", "")
    assert eob != chk


def test_the_1095_health_coverage_form_is_a_tax_document():
    for title in ["1095-B Health Coverage", "IRS Form 1095-B"]:
        cat, summary, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title


def test_no_leftover_vocabulary_from_the_app_this_was_cloned_from():
    """Cloned from the DFAS myPay app. A health-insurance member has no
    retirement-pay statements, so that vocabulary must not linger in the rules."""
    rules_text = (Path(__file__).resolve().parents[1] / "document_rules.json").read_text(encoding="utf-8")
    for word in ("crsc", "eras", "retiree", "1099-r", "sgli", "leave and earnings"):
        assert word not in rules_text.lower(), word


# -- SAFETY: the Anthem portal can change care, coverage and settings -------

def test_health_portal_action_controls_are_never_safe():
    for label in [
            # care and coverage
            "Find Care", "Find a Doctor", "Change PCP", "Select PCP",
            "Refill Prescription", "Order a new ID card", "Request a card",
            "Appeal this claim", "File a Grievance", "Prior Authorization",
            "Schedule an appointment", "Start a chat", "Message your care team",
            "Send a message",
            # enrollment / plan / money
            "Enroll now", "Switch Plan", "Pay premium", "Make a payment",
            "Manage AutoPay", "Submit a claim", "File a claim",
            "Go 100% Digital", "Go Paperless", "Manage Paperless EOBs",
            "Set up now",
            # identity / settings
            "Change Address", "Update Email", "Change Password",
            "Security Question",
            # consent and commit verbs
            "Agree to Terms", "I Accept", "Consent", "Submit", "Confirm",
            "Save Changes", "Manage Settings", "Turn off", "Opt Out",
            "Certify", "Authorize"]:
        assert not site.is_safe_control(label), label


def test_the_documents_the_user_wants_are_allowed():
    for label in ["Download EOB", "Download EOB Check", "View Medical EOBs",
                  "View Pharmacy EOBs", "Download PDF", "Open PDF", "Print",
                  "Explanation of Benefits", "View Document",
                  "1095-B Health Coverage Form"]:
        assert site.is_safe_control(label), label


def test_the_eob_check_noun_is_not_mistaken_for_a_verb():
    """"Check" in "EOB Check" is the reimbursement-check noun, not a command,
    so it stays downloadable - the verb-vs-noun care the repo learned the hard
    way."""
    assert site.is_safe_control("Download EOB Check")
    assert site.is_safe_control("Explanation of Benefits Check")


def test_deny_by_default():
    for label in ["", "   ", "More", "Go", "Help", "Menu", "OK", "Yes",
                  "Español"]:
        assert not site.is_safe_control(label), label


# -- SAFETY: a document is fetched by a validated identity, never a URL ------

def test_a_document_is_fetched_by_a_validated_identity_never_by_a_url():
    """Identity is "claimType|claimId|docKind": the claim type and kind must be
    ones this app knows and the claim number is validated to Anthem's
    alphanumeric shape, so nothing a stored or tampered value could contain can
    steer the request elsewhere."""
    assert site.parse_doc_id("Medical|1234500AA0001|EOB") == \
        ("Medical", "1234500AA0001", "EOB", 0)
    assert site.parse_doc_id("Pharmacy|1234500DD0004|EOB Check") == \
        ("Pharmacy", "1234500DD0004", "EOB Check", 0)
    assert site.parse_doc_id("Medical|1234500AA0001|EOB|1") == \
        ("Medical", "1234500AA0001", "EOB", 1)
    for bad in [
            "Dental|1234500AA0001|EOB",           # unknown claim type
            "Medical|1234500AA0001|Letter",        # unknown doc kind
            "Medical||EOB",                        # empty claim number
            "Medical|1234500AA0001",               # missing kind
            "Medical|2026 217|EOB",                # space in claim number
            "Medical|../etc/passwd|EOB",           # path traversal
            "Medical|1234500AA0001|EOB OR 1=1",    # injection
            "https://evil.test/Medical|x|EOB",
            "Medical|1234500AA0001|EOB|x",         # non-numeric ordinal
            "", "Medical", "|1234500AA0001|EOB"]:
        assert site.parse_doc_id(bad) is None, bad


def test_the_identity_is_the_claim_not_the_transient_eobid():
    """The opaque eobId is a per-session token; a stored one goes stale. The
    identity is (claimType, claimId, docKind, seq) and the eobId is looked up
    fresh at download time - the myPay transient-Id lesson, carried over."""
    src = (Path(__file__).resolve().parents[1] / "anthem_site.py").read_text(encoding="utf-8")
    assert "def resolve_eob_id" in src
    assert "resolve_eob_id(page, claim_type, claim_id, doc_kind, seq)" in src
    # the collector must build its identity from the claim, never from eobId
    assert "make_doc_id(row[\"claim_type\"], row[\"claim_id\"]," in src
    # and the stored doc_id must not embed the eobId
    assert "eob_id" not in site.make_doc_id("Medical", "1234500AA0001", "EOB")


def test_the_claim_types_are_the_portals_own_three():
    assert site.CLAIM_TYPES == ["Medical", "Pharmacy", "Chiropractic"]


# -- SAFETY: host + frame guards --------------------------------------------

def test_urls_must_stay_on_anthems_hosts():
    assert site.is_safe_url("https://membersecure.anthem.com/member/claims")
    assert site.is_safe_url("https://membersecure-polaris.anthem.com/api/claims/trpc/eob.v1.summary")
    for bad in ["https://membersecure.anthem.com.evil.test/x",
                "https://membersecure.anthem.com@evil.test/x",
                "http://membersecure.anthem.com/x",
                "https://anthem.com/x",           # bare host is not one we call
                "https://evil.test/x",
                "//evil.test/x",
                "javascript:alert(1)",
                ""]:
        assert not site.is_safe_url(bad), bad


def test_only_anthem_frames_are_read():
    class F:
        def __init__(self, url): self.url = url
    assert site.is_anthem_frame(F("https://membersecure.anthem.com/member/claims"))
    assert site.is_anthem_frame(F("https://membersecure-polaris.anthem.com/api/claims"))
    for bad in ["https://mail.google.com/", "about:blank", "",
                "http://membersecure.anthem.com/x",
                "https://membersecure.anthem.com.evil.test/x"]:
        assert not site.is_anthem_frame(F(bad)), bad


# -- SAFETY: never fills, submits or confirms; only clicks guarded downloads --

def test_the_app_never_fills_submits_confirms_or_clicks():
    """The app must never fill a field, submit a form, tick a checkbox, confirm a
    dialog, or CLICK anything on a health account - those are the actions that
    could change care or coverage. Every document (EOB, member document, ID card,
    letter) is fetched by the portal's own read-only API from inside the page, so
    there is no control to mis-fire at all."""
    src = (Path(__file__).resolve().parents[1] / "anthem_site.py").read_text(encoding="utf-8")
    for forbidden in (".check(", ".fill(", ".type(", ".select_option(",
                      ".set_checked(", ".press(", ".click(", "on(\"dialog\"",
                      "expect_download"):
        assert forbidden not in src, forbidden


def test_the_guard_still_refuses_care_and_coverage_controls():
    """The app clicks nothing, but the read-only guard is kept as a contract:
    a control that changes care or coverage must never pass is_safe_control, and
    the plain document actions a member wants must."""
    for allowed in ["Download EOB", "Download PDF", "View Document",
                    "Open PDF", "1095-B Tax Form"]:
        assert site.is_safe_control(allowed), allowed
    for denied in ["Go Paperless", "Change Plan", "Order a new ID card",
                   "Send a message", "Pay premium"]:
        assert not site.is_safe_control(denied), denied


def test_member_document_labels_route_to_the_right_folder():
    assert site.document_folder_for("Proof of Insurance") == "plan_documents"
    assert site.document_folder_for("Plan Confirmation") == "plan_documents"
    assert site.document_folder_for("1095-B Tax Form") == "tax_documents"
    assert site.document_folder_for("Tax Document 2025") == "tax_documents"
    assert site.document_folder_for("Prior Authorization Approval") == "authorizations"
    assert site.document_folder_for("Referral Letter") == "authorizations"


def test_navigation_only_targets_a_host_checked_url():
    """The one navigation the app makes (to prime the session) must go to this
    app's own EOB-center URL, which is host-checked, never to a stored value."""
    src = (Path(__file__).resolve().parents[1] / "anthem_site.py").read_text(encoding="utf-8")
    # the goto target is built from URLS["documents"] and guarded by is_safe_url
    assert 'target = URLS["documents"]' in src
    assert "if not is_safe_url(target)" in src
    assert "page.goto(target" in src


def test_no_screenshot_of_a_phi_page_is_written():
    """A screenshot of the member portal shows claims, providers and diagnoses
    (PHI), and would sit in Diagnostics where it is easy to attach to a bug
    report by accident."""
    src = (Path(__file__).resolve().parents[1] / "anthem_docs.py").read_text(encoding="utf-8")
    assert "page.screenshot(" not in src


# -- SAFETY: a signed-out session must be recognised, not reported as empty --

def test_a_signin_page_returned_instead_of_a_pdf_is_recognised():
    """An expired session answers with HTML (an Akamai block or a sign-in page),
    and if that is not spotted the run reports an empty success."""
    assert site._looks_like_login_html(
        b"<!DOCTYPE html><html><body><form><input type=\"password\"></form>")
    assert site._looks_like_login_html(b"<html>Access Denied</html>")
    assert not site._looks_like_login_html(b"%PDF-1.7 real document")
    assert not site._looks_like_login_html(b"")


def test_akamai_block_and_mfa_pages_are_treated_as_challenges():
    """The Akamai block page ("Access Denied" / "Reference #") and the MFA
    prompt must both stop a run loudly. detect_security_challenge reads these
    off the page body; the markers must be present."""
    for marker in ("access denied", "reference #", "verification code",
                   "remember this device"):
        assert marker in site.SECURITY_CHALLENGE_MARKERS, marker


# -- the defensive summary parser (response shape unconfirmed at recon) ------

def test_the_summary_list_is_found_inside_a_trpc_envelope():
    """The response body was not observed at recon, so the parser walks to the
    first list-of-dicts rather than assuming an envelope. It must find the rows
    whether they sit bare, under result/data, or superjson-wrapped under json."""
    rows = [{"claimId": "A1", "eobId": "tok"}]
    assert site._walk_for_list(rows) == rows
    assert site._walk_for_list({"result": {"data": rows}}) == rows
    assert site._walk_for_list({"result": {"data": {"json": rows}}}) == rows
    assert site._walk_for_list({"result": {"data": {"eobs": rows}}}) == rows
    assert site._walk_for_list({}) == []


def test_a_row_missing_a_required_field_is_skipped_not_guessed(caplog):
    """If neither the claim id nor the eob id is present under any known name,
    the row is dropped and its raw keys are logged so the pilot reveals the real
    field name - never silently collected as an empty document."""
    import logging
    good = {"claimId": "1234500AA0001", "eobId": "opaque-token",
            "eobStatementDate": "2026-08-05T00:00:00"}
    row = site._extract_row(good, "Medical")
    assert row["claim_id"] == "1234500AA0001"
    assert row["eob_id"] == "opaque-token"
    assert row["date"] == "2026-08-05"
    assert row["doc_kind"] == "EOB"
    with caplog.at_level(logging.ERROR):
        assert site._extract_row({"somethingElse": 1}, "Medical") is None
    assert "missing a claim number" in caplog.text


class _FakePage:
    """A stand-in for a Playwright page: it is on an Anthem host and answers an
    eob.v1.summary evaluate() with canned tRPC rows per claim type."""

    def __init__(self, url, summary_by_type):
        self.url = url
        self._summary = summary_by_type

    def evaluate(self, js, arg=None):
        rows = self._summary.get((arg or {}).get("claimType"), [])
        return {"status": 200, "body": {"result": {"data": rows}}}


def test_two_same_date_claims_stay_distinct_on_disk():
    """Two EOBs can share a statement date (the recon showed two Medical claims
    on 2026-07-16). Their identities and their filenames must both stay distinct
    and stable across runs, so the claim number rides into the filename via the
    `account` field. mypay's suite proves the account->filename half; this proves
    collect_documents supplies the disambiguator."""
    page = _FakePage("https://membersecure.anthem.com/member/claims/eob-center", {
        "Medical": [
            {"claimId": "1234500CC0003", "eobId": "tokA",
             "eobStatementDate": "2026-07-16"},
            {"claimId": "1234500DD0004", "eobId": "tokB",
             "eobStatementDate": "2026-07-16"},
        ],
    })
    rows = site.collect_documents(page)
    assert len(rows) == 2
    # distinct stable identities
    assert rows[0]["doc_id"] != rows[1]["doc_id"]
    assert {r["doc_id"] for r in rows} == {
        "Medical|1234500CC0003|EOB|0", "Medical|1234500DD0004|EOB|0"}
    # each account carries its own claim number, so the engine's filename
    # (summary + account) cannot collide
    assert rows[0]["account"] != rows[1]["account"]
    assert "1234500CC0003" in rows[0]["account"]
    assert "1234500DD0004" in rows[1]["account"]
    # and the eobId is nowhere in the stored identity
    for r in rows:
        assert "tok" not in r["doc_id"]


def test_the_patient_name_rides_into_the_filename_on_a_family_plan():
    """On a plan covering more than one person, each member's EOBs must be
    distinguishable. The patient name is captured (defensively) and carried in
    the `account` field, which the engine suffixes into the filename. A trailing
    date of birth is trimmed so it never lands in a filename."""
    page = _FakePage("https://membersecure.anthem.com/member/claims/eob-center", {
        "Medical": [
            {"claimId": "1234500AA0001", "eobId": "tokA",
             "eobStatementDate": "2026-08-05", "patientName": "JANE DOE 01/01/2010"},
            {"claimId": "1234500BB0002", "eobId": "tokB",
             "eobStatementDate": "2026-08-05", "patientName": "JOHN DOE"},
        ],
    })
    rows = site.collect_documents(page)
    by_claim = {r["doc_id"]: r for r in rows}
    child = by_claim["Medical|1234500AA0001|EOB|0"]
    parent = by_claim["Medical|1234500BB0002|EOB|0"]
    assert child["account"].startswith("Jane Doe -")   # all-caps tidied, DOB trimmed
    assert "01/01/2010" not in child["account"]
    assert parent["account"].startswith("John Doe -")
    # different people -> different filenames even on the same date, and the
    # EXACT claim number survives (the engine no longer title-cases the account,
    # which would corrupt 1234500AA0001 -> 1234500Aa0001).
    storage.set_filename_owner("")
    import re as _re
    def _fname(account):
        a = _re.sub(r"\b(COMBINED|ACCOUNTS?)\b", "", account, flags=_re.I)
        a = _re.sub(r"\s+", " ", a).strip()   # matches the engine: no .title()
        return build_pdf_filename("2026-08-05", f"Explanation of Benefits - {a}", "")
    fc, fp = _fname(child["account"]), _fname(parent["account"])
    assert fc != fp
    assert "1234500AA0001" in fc    # exact claim number, not title-cased
    assert "1234500BB0002" in fp


def test_a_missing_patient_name_falls_back_to_claim_only():
    page = _FakePage("https://membersecure.anthem.com/member/claims/eob-center", {
        "Medical": [
            {"claimId": "1234500AA0001", "eobId": "tokA",
             "eobStatementDate": "2026-08-05"},
        ],
    })
    row = site.collect_documents(page)[0]
    assert row["account"] == "Medical claim 1234500AA0001"


def test_an_eob_and_its_check_on_one_claim_get_distinct_identities():
    page = _FakePage("https://membersecure.anthem.com/member/claims/eob-center", {
        "Medical": [
            {"claimId": "1234500DD0004", "eobId": "tokA",
             "eobStatementDate": "2026-07-16", "documentType": "EOB"},
            {"claimId": "1234500DD0004", "eobId": "tokB",
             "eobStatementDate": "2026-07-16", "documentType": "EOB Check"},
        ],
    })
    rows = site.collect_documents(page)
    assert {r["doc_id"] for r in rows} == {
        "Medical|1234500DD0004|EOB|0", "Medical|1234500DD0004|EOB Check|0"}


# -- the confirmed live schema (deep recon 2026-08-31) ----------------------

def test_the_confirmed_live_summary_row_shape_is_parsed():
    """The real eob.v1.summary row: identifier = eobId, claim number nested at
    claim[0].identifier[*].value, created = date, patient.name = patient,
    supportingInfo.eobSubType distinguishes an EOB from a reimbursement Check."""
    row = {
        "identifier": "Z_QKxcJl27UXyqqNLkp5" + "x" * 172,   # ~192-char opaque token
        "created": "2026-08-09T00:00:00",
        "checkDate": "2026-08-11",
        "eobSequenceNbr": 2,
        "patient": {"name": "JANE DOE"},
        "supportingInfo": {"eobSubType": "HealthCareSummary"},
        "claim": [{"identifier": [
            {"system": "urn:anthem:eob", "value": "5550000"},
            {"system": "urn:anthem:claim", "value": "1234500AA0001"},
        ]}],
    }
    got = site._extract_row(row, "Medical")
    assert got["claim_id"] == "1234500AA0001"      # the letter+digit identifier
    assert got["eob_id"].startswith("Z_QKxcJl")     # the opaque token
    assert got["date"] == "2026-08-09"
    assert got["doc_kind"] == "EOB"
    assert got["patient"] == "JANE DOE"
    assert got["seq"] == 2

    check = dict(row, supportingInfo={"eobSubType": "Reimbursement"})
    assert site._extract_row(check, "Medical")["doc_kind"] == "EOB Check"


def test_the_lookback_window_is_capped_at_24_months():
    """The API returns an EMPTY list once start is older than ~25 months (30mo
    and 36mo both returned zero live), so the window must not exceed ~24 months
    or a run would silently fetch nothing."""
    assert site.DEFAULT_LOOKBACK_DAYS <= 25 * 30
    start, end = site._date_window()
    assert start < end


def test_the_pdf_is_taken_from_the_download_envelopes_file_field():
    """The download returns {result:{data:{file: <base64 PDF>}}}, not raw bytes.
    The download JS must extract result.data.file and Python must base64-decode
    and verify %PDF before writing."""
    src = (Path(__file__).resolve().parents[1] / "anthem_site.py").read_text(encoding="utf-8")
    assert "result.data.file" in src or "result && j.result.data && j.result.data.file" in src
    assert "base64.b64decode" in src
    assert 'body.startswith(b"%PDF")' in src


def test_auth_headers_are_captured_in_page_not_lifted_into_python():
    """The bearer token is captured from the SPA's own request by an in-page
    XHR/fetch hook into window.__eobHeaders and read there; it must not be
    pulled into this process. The summary/download JS reference the in-page
    header store, and no Python code reads an authorization value."""
    src = (Path(__file__).resolve().parents[1] / "anthem_site.py").read_text(encoding="utf-8")
    assert "window.__eobHeaders" in src
    assert "XMLHttpRequest.prototype.setRequestHeader" in src
    # Python never reads the auth header off the request - that would lift the
    # token into this process. It stays in window.__eobHeaders, used in-page.
    for py_leak in ("all_headers()", "request.headers", ".get('authorization'",
                    '.get("authorization"'):
        assert py_leak not in src, py_leak
