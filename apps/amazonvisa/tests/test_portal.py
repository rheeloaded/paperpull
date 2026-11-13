"""Exercise the in-page document bridge with invented portal responses."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import amazonvisa_site as site


HARNESS = r"""
const bridge = eval("(" + require("fs").readFileSync(0, "utf8") + ")");
const mode = process.argv[1];
global.location = {origin: "https://kunden.openbankpay.com", pathname: "/amazon/documentation"};
const bucket = "prod-de-mbgdcs-documents01.s3.eu-west-1.amazonaws.com";
const calls = [];
const ticket = "https://" + (mode === "foreign" ? "example.invalid" : bucket) +
               "/invented.pdf?X-Amz-Signature=INVENTED_SIGNATURE";
const row = (id, ext = ".pdf") => ({id, date: "2026-02-03", fileExtension: ext});
// In "hangs" mode the portal never answers, and a wait of the bridge's
// is cut short so the test does not sit through it.
const realSetTimeout = setTimeout;
global.setTimeout = (fn, ms, ...rest) => realSetTimeout(fn, mode === "hangs" ? 5 : ms, ...rest);
const client = {get: async ({endpoint, pathParams}) => {
  calls.push(endpoint);
  if (mode === "hangs") return new Promise(() => {});
  if (mode === "signed-out") return [{}, {status: 401}];
  if (mode.startsWith("ticket-") && /(versions\/:version|uri\/:id)$/.test(endpoint))
    return [{}, {status: Number(mode.slice(-3))}];
  let data;
  if (endpoint.endsWith("/global-position")) {
    data = {resource: {cardsInfo: {cards: [
      {cardContractId: "contract1"}, {cardContractId: "contract1"}, {cardContractId: "contract2"}
    ]}}};
  } else if (endpoint.endsWith("/statements")) {
    data = {metadata: {hasPendingRecords: mode === "pending"},
            elements: [{documentId: "s-" + pathParams.cardContractId, version: "1",
                        statementDate: "2026-03-01"}]};
  } else if (endpoint.endsWith("/categories")) {
    data = {categories: ["cat_contratos", "cat_identificativo"]};
  } else if (endpoint.endsWith("/v4/documents")) {
    data = {documents: [row("other"), row("html", ".html")], size: mode === "partial" ? 3 : 2};
  } else if (endpoint.endsWith("/versions/:version")) {
    data = {documentUri: ticket};
  } else if (endpoint.endsWith("/uri/:id")) {
    data = {uri: ticket};
  } else {
    throw new Error("unexpected route");
  }
  return [data, {status: 200}];
}};
global.window = {webpackChunk_openbank_ui_clients: {push: (chunk) => chunk[2](() => ({Tz: client}))}};
let fetched = 0;
global.fetch = async (url, options) => {
  fetched++;
  if (url.hostname !== bucket || options.credentials !== "omit" ||
      options.redirect !== "error" || options.referrerPolicy !== "no-referrer")
    throw new Error("unsafe PDF request");
  return new Response("%PDF-1.4\nInvented");
};
(async () => {
  const listed = await bridge({op: "collect"});
  const downloaded = listed.ok && ["download", "document", "foreign", "ticket-401", "ticket-403"].includes(mode)
    ? await bridge({op: "download", id: mode === "document" ? "document:other" : listed.rows[0].item_id})
    : null;
  console.log(JSON.stringify({listed, downloaded, fetched, calls}));
})().catch(() => process.exit(1));
"""


def run_bridge(mode):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise the in-page bridge")
    result = subprocess.run([node, "-e", HARNESS, mode],
                            input=site.intake.reading(site._API_JS), encoding="utf-8",
                            capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


def test_lists_each_contract_and_deduplicates_documents_across_categories():
    result = run_bridge("collect")["listed"]
    assert result["ok"]
    assert result["summary"]["contracts"] == 2
    assert len(result["rows"]) == 3
    assert result["summary"]["non_pdf"] == 2
    assert {row["item_id"] for row in result["rows"]} == {
        "statement:s-contract1:1", "statement:s-contract2:1", "document:other",
    }


@pytest.mark.parametrize("mode", ["partial", "pending", "signed-out"])
def test_incomplete_or_signed_out_listing_does_not_return_rows(mode):
    result = run_bridge(mode)["listed"]
    assert not result["ok"]
    assert result["expired"] == (mode == "signed-out")
    assert "rows" not in result


@pytest.mark.parametrize("mode", ["download", "document"])
def test_both_ticket_types_download_pdfs_without_returning_the_signed_url(mode):
    result = run_bridge(mode)
    assert result["fetched"] == 1
    assert result["downloaded"]["data"].startswith("JVBERi0")
    assert "INVENTED_SIGNATURE" not in json.dumps(result)


def test_a_signed_url_on_an_unlisted_host_is_refused_before_fetch():
    result = run_bridge("foreign")
    assert not result["downloaded"]["ok"]
    assert result["fetched"] == 0


@pytest.mark.parametrize("mode", ["ticket-401", "ticket-403"])
def test_a_refused_ticket_is_that_documents_failure_and_not_a_sign_out(mode):
    """A 401 or 403 on one document's ticket read as signed out, so the run
    stopped there without the list being asked. It is that document's own
    failure, and the list read again says whether the session ended."""
    result = run_bridge(mode)
    assert result["listed"]["ok"]
    assert result["downloaded"] == {"ok": False, "expired": False,
                                    "error": "The portal refused this document"}
    assert result["fetched"] == 0


def test_a_portal_that_never_answers_is_given_up_on():
    """The portal's client takes no signal, so a call that never answered
    held the run there for good."""
    result = run_bridge("hangs")["listed"]
    assert not result["ok"] and not result["expired"]
    assert result["error"] == "The portal did not answer in time"
    assert "rows" not in result
