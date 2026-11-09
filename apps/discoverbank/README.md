# Discover Bank statement downloader

Downloads your Discover Bank **checking and savings** account statements as
PDFs from `bank.discover.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

Contributed by [@appchamp](https://github.com/appchamp), whose full run on
their own accounts saved 100 checking statements (2018-07 to 2026-10) and
100 savings statements (2017-11 to 2026-10), each a valid PDF filed under
its own account ([#151](https://github.com/rheeloaded/paperpull/pull/151)).

**Scope.** Discover Bank deposit accounts. Checking and online savings are
confirmed on a real account. Money market and CD accounts are read the same
way but have not been seen yet. Tax forms are not collected.

**Discover credit cards are a different app.** A Discover card is read on
`card.discover.com` by [`discovercard`](../discovercard), and a card that
has moved to Capital One by [`capitalone`](../capitalone). The two Discover
apps are separate installs with separate sign-in windows, and this one never
opens the card site.

## Setup

```bash
./setup.command                   # one-time: venv + Playwright
./login.command                   # opens Edge/Chrome on port 9306, sign in yourself
paperpull discoverbank diagnose   # a safe look: reads the page, downloads nothing
paperpull discoverbank pilot      # download the newest few as a test
paperpull discoverbank all        # download everything available
```

(On Windows, the matching `setup.bat`, `login.bat` and the rest. `setup` does
not create `config.json`, so copy it once with `cp config.example.json config.json`.)

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), like the
Walmart, Verizon and Chase apps, never the bundled Playwright Chromium.

## How it works

- **You sign in.** The tool attaches over CDP to the window you signed into and
  only reads. It never sees a password and never touches 2FA.
- **The page** is *Statements* at
  `https://bank.discover.com/web/deposits/documents/statements`, opened by
  its address.
- **The accounts** are read from the page's own account menu, from the
  state the page keeps for it, never by opening the menu or choosing an
  account on it. Every option that is a deposit account is read, with the
  id the page asks its statement list by.
- **Each account's list** is the page's own call,
  `/bank/deposits/servicing/documents/v1/accounts/{accountId}/statements`,
  asked from inside the page with its session. A statement is kept only when
  its PDF sits under that same account, its date is a real day, and the
  account's name and the product code in its id (`~OC~` checking, `~OSA~`
  savings) agree on its kind. The account's name from the menu goes into the
  file name, `2026-10-31 Discover Bank Checking Statement - Checking (••••1234).pdf`
  by default.
- **A list read in part is never called whole.** An account whose list did
  not answer, an account with no id or with the same name as another, an
  option whose name says an action rather than an account, and a statement
  that cannot be told apart, are each a part of the list missing.
  What was read is downloaded, a failure file is written, and the run stops
  at its end rather than finish, so Resume reads the list again first.
- **With no account menu to read**, the one statement list the page asked
  for itself is read, and the run still stops at its end, since how many
  accounts there are is then not known. With no list either, the run stops
  with nothing downloaded and says so.
- **Download is an authenticated in-page fetch** of the address the list
  gave, which must be a statement PDF on `bank.discover.com`. Bytes must start
  with `%PDF-` before anything is written to disk.
- **Read-only.** Nothing on the page is pressed. The guards refuse transfers,
  wires, Zelle, payments and profile changes, and `card.discover.com` and
  `cards.discover.com` are refused hosts.

## Repairing it when Discover changes the site

Everything provider-specific is in
[`discoverbank_site.py`](discoverbank_site.py). Sign in, open Statements,
run `paperpull discoverbank diagnose` (it downloads nothing) and read
`Diagnostics/diagnose-documents.json`. Its `statements_api` part reports
whether the account menu was read, how many accounts it holds and of what
kind, how many statements their lists name, the date range, the shape of a
PDF's address, and anything passed over.

## Notes

- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `paperpull discoverbank add-account NAME`). Identity lives in `progress.json`,
  each statement known by the address its list gives for its PDF.
- **Not yet confirmed.** Whether those addresses stay the same after a new
  sign-in is not known yet. A second run on the contributor's accounts after signing in again
  should download nothing new. If it downloads everything again, please
  open an issue.
- **App slug.** `discoverbank`, beside the card app `discovercard`.
