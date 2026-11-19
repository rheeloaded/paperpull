# BBVA Germany

Downloads existing PDFs from the web Postfach, including account statements
and PDF attachments to bank communications. It follows the Postfach's
pagination across the available history. Requested in
[issue #209](https://github.com/rheeloaded/paperpull/issues/209).

The default CDP port is **9317**. Run setup once with Python 3.11 or later.

```sh
./paperpull --root ./apps bbva setup
```

```sh
cp apps/bbva/config.example.json apps/bbva/config.json
```

```sh
./paperpull --root ./apps bbva login
```

Sign in yourself and leave the BBVA web window open.

```sh
./paperpull --root ./apps bbva discover
```

```sh
./paperpull --root ./apps bbva pilot
```

Use `all` for a full download, `resume` to continue an interrupted run, and
`verify` to check saved PDFs. The local progress file lets later runs skip
documents already downloaded.

PaperPull uses the signed-in portal client for GET requests to the Postfach
list, message details and PDF endpoints. It leaves the portal's separate
mark-as-read action alone. Messages without PDF attachments are reported.
The session and request headers stay in the browser.

Live validation on 2026-11-19 found 24 PDFs across two pages in one
contributor's account. Discover completed without errors; the local catalogue
still held 26 entries from earlier runs. The first pilot selected five
PDFs, saved and verified two new files, and skipped three already saved.
The second pilot saved no new files. Both pilots reported zero failures,
validation failures, manual reviews and stopped runs.

All 24 current PDFs were delivered inline. Message attachments delivered
as links and standalone correspondence PDFs are covered by automated tests;
the linked-message case still needs a live example. A full download,
additional accounts and other product types have yet to be tested.
