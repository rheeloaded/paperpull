"""Exercise the portal bridge with invented BBVA Postfach answers."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bbva_site as site


HARNESS = r"""
const fs = require("fs");
const source = fs.readFileSync(0, "utf8");
const mode = process.argv[1];
global.location = {origin: "https://web.bbva.de", pathname: "/index.html"};
global.window = {};
const api = "https://de-net.bbva.com";
const list = api + "/notifications/v0/virtual-mails";
global.performance = {getEntriesByType: () => [
  {name: location.origin + "/js/icon-grTest.js"},
  {name: list + "?customerId=invented"}
]};
const pdf = Buffer.from("%PDF-1.4\nInvented").toString("base64");
const sent = [];
const row = (id, origin) => ({id, origin, subject: "Kontoauszug", sendDate: "2026-10-01",
                              document: {id: origin === "CORRESPONDENCE" ? "document-" + id : ""}});
const mockClient = {aso: {request: async ({url, method, isDownload}) => {
  if (method !== "GET") throw Error("write requested");
  sent.push(url);
  const u = new URL(url);
  if (mode === "expired") throw {xhr: {status: 401}};
  let model;
  if (u.pathname === "/notifications/v0/virtual-mails") {
    if (u.searchParams.get("paginationKey") === "000000000-0") {
      model = {data: [row("one", "COMMUNICATION")], pagination: {nextPage:
        (mode === "foreign" ? "https://example.invalid" : api) +
        u.pathname + "?customerId=invented&paginationKey=next&pageSize=20"}};
    } else {
      model = {data: [row(mode === "duplicate" ? "one" : "two", "CORRESPONDENCE")]};
    }
  } else if (u.pathname === "/announcements/V01/one/") {
    model = {attachments: [{name: "statement.pdf", contentFile: pdf}]};
  } else if (u.pathname === "/bankingVirtualMails/V02/document-two/bankingVirtualDocument/" && isDownload) {
    model = new Blob([Buffer.from(pdf, "base64")], {type:"application/pdf"});
  } else throw Error("unexpected route");
  return {xhr: {status: 200}, model};
}}};
const bridge = eval("(" + source.replace("await import(module.pathname)", "({r: mockClient, i: () => {}})") + ")");
(async () => {
  const listing = await bridge({op: "collect"});
  let downloads = [];
  if (listing.ok) for (const row of listing.rows)
    downloads.push(await bridge({op: "download", id: row.item_id}));
  console.log(JSON.stringify({listing, downloads, sent}));
})().catch(() => process.exit(1));
"""


def run(mode):
    import json
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise the in-page bridge")
    result = subprocess.run([node, "-e", HARNESS, mode], input=site.intake.reading(site._API_JS),
                            encoding="utf-8", capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


def test_reads_all_pages_and_downloads_inline_and_standalone_pdfs():
    result = run("collect")
    assert [row["item_id"] for row in result["listing"]["rows"]] == ["message:one:0", "document:document-two"]
    assert len(result["downloads"]) == 2
    assert all(pdf["data"].startswith("JVBERi0") for pdf in result["downloads"])


@pytest.mark.parametrize("mode", ["foreign", "duplicate", "expired"])
def test_refuses_incomplete_or_off_host_lists(mode):
    result = run(mode)
    assert not result["listing"]["ok"]
    assert result["listing"]["expired"] == (mode == "expired")
    assert not any("example.invalid" in url for url in result["sent"])
    assert not result["downloads"]
