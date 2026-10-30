# Security & privacy

These tools sign in to **real financial and shopping accounts** and download
**real statements and receipts**. Treat this repository accordingly.

PaperPull Server, the edition you run on a machine at home, listens on your
network where the desktop app does not, and has a page of its own,
[SECURITY-SERVER.md](SECURITY-SERVER.md).

## What must never be committed

The `.gitignore` already blocks all of the following. Do not override it.

- **Browser profile folders** (`*-browser-profile/`), these hold live logged-in
  sessions: cookies and auth tokens for your bank, brokerage, and Amazon. This
  is the single worst thing that could leak. Anyone with them can act as you.
- **`config.json` / `config.<account>.json`**, your real paths and account
  labels. Only the sanitized `config.example.json` is tracked.
- **Downloaded documents** (`*.pdf`, `*.zip`), your actual financial records.
- **Runtime state**, `discovery.json`, `progress.json`, `*.log`, `*.csv`,
  `Diagnostics/` (which can contain screenshots of signed-in pages), `Backups/`.

## Before your first commit

1. Confirm nothing sensitive is staged: `git status` should show only source,
   docs, and `config.example.json`.
2. If you ever accidentally commit a secret, deleting it in a later commit is
   **not enough**, it stays in git history. Scrub history (e.g. with
   `git filter-repo`) or start a fresh repo.

## Design safety (what the tools themselves do)

- **Read-only.** There is no code anywhere that moves money or changes a
  setting, and with one documented exception, none that submits a form or
  confirms a dialog. The exception: AAFMAA interposes a disclosure dialog
  ("I confirm that I have read the message above") before serving some
  documents, and the AAFMAA app may tick that checkbox and click View. The
  dialog changes nothing on the account, and the app checks the dialog's id,
  requires the disclosure's own sentence in its text, and refuses it if a
  single money-related word appears. A dialog left over from an earlier
  document is cleared by reloading, never answered, because its View button
  belongs to a different document. How the read-only rule is enforced
  elsewhere depends on
  how the provider exposes its documents:

  - **Apps that hold a control to an allowlist** (AAFMAA, ADP, Ally, Alpaca,
    American Family, Apple Card, AT&T, Bank of America, Best Buy, Bilt, Chase, Chase Business,
    Coinbase, Costco, Discover, Dominion, eBay, E*TRADE, Fairfax Water, First
    Horizon, Golden 1, Interactive Brokers, M&T, Meijer, Nelnet, Newrez,
    PayPal, PG&E, RedCard, SBA, Shelby County, Simmons Bank, SMUD, Spectrum,
    State Farm, T-Mobile, TreasuryDirect, U.S. Bank, Vanguard, Venmo, Verizon
    Mobile and Wells Fargo) decide which of the page's controls may be
    pressed with `is_safe_control()`, a hard blocklist (`FORBIDDEN_CONTROL_RE`,
    buy/sell/transfer/pay/delete/change-setting) **plus** a document
    allowlist (`SAFE_DOC_CONTROL_RE`). A control must pass **both**, so
    anything unrecognized is refused, deny by default. AAFMAA runs the same
    two patterns inline. Alpaca, Best Buy, Bilt, Chase Business, First
    Horizon, Simmons Bank, Spectrum, TreasuryDirect and Venmo narrow the
    allowlist to the whole labels they press, and all of them but
    TreasuryDirect give each control a guard of its own built the same way.
    Best Buy presses only its year menu and a year in it. Bank of America
    presses only the Statements heading of its statements page, a button
    whose whole name is Statements and which says it is shut, when the page
    shows no Download PDF link, and again after a later reload shuts it,
    never one a press would submit a form with, and one statement's
    Download PDF link once a run, when every link's address is a script, a
    link and not a button whose words beside the bank's own names for the
    statements and accounts it listed pass both patterns. It keeps nothing
    that press brought, cancels the download and closes the tab it opened,
    and asks for every list and PDF from inside the page. M&T presses only
    the year headings of its statements list, and since a year is no
    document word, `is_safe_control()` would refuse them. So the heading
    has a guard of its own, the blocklists plus its whole words, a year
    with at most the few words a heading carries beside it, and a year left
    closed stops the run rather than leave the list short. Besides those,
    an app may press a control it finds by a selector or by words written
    in the app, such as a session dialog's "Continue session", an
    accordion, a year menu or a list's "Next", which a document allowlist
    would refuse.
  - **Apps that press only controls they find themselves** (Amex, Capital
    One, Navy Federal, Robinhood, Schwab, Target, USAA, Verizon, Walmart and
    Wealthfront) call no `is_safe_control()` during a run. They press
    controls they find by a selector or by words written in the app, such as
    a statement row by its test id, a link that says Statements, a "Next
    page" button or a year menu. Capital One and Schwab press nothing but
    their own "continue session" dialog. Target and Walmart, whose order
    pages are printed, have no `is_safe_control()` at all. They press
    fixed controls (the purchase history tabs, a year menu, Load more, a
    list's Next, the items toggle) and check every receipt control against
    the blocklist inline, since a document allowlist would refuse the paging
    they need.
  - **Apps that click nothing at all during a run** (Affirm, Amazon, Anthem,
    Apple, Citi, E-ZPass Virginia, FedEx, Fidelity, Gap, GitHub, Home Depot,
    Invest529, IRS, Kroger, Lowe's, MILITARY STAR, myPay, NetBenefits, Optum
    Bank, Paylocity, Portland General Electric, SDG&E, Stripe, TSP, Uber, UKG
    and UPS) open the provider's
    pages by their address and read them, or ask for the same lists and
    files the provider's own page asks for, from inside the signed-in page or
    with its cookies. On a site that can also change direct deposit and tax
    withholding, not activating a control is the strongest guarantee
    available, and UKG additionally refuses any URL whose path says `EDIT`
    rather than `VIEW`. The Diagnose command of Affirm, Fidelity, Invest529,
    NetBenefits and TSP, run by hand to help repair a provider, may follow up to six
    links whose whole text is a section name it knows, such as Statements or
    Documents, each through `is_safe_control()`.
  - **Every app has a host allowlist.** A stored or page-supplied URL that
    resolves to any other host is refused before the browser goes there. A
    repo-wide test (`core/tests/test_every_app_guard.py`) checks that every
    app has the allowlist and a working guard, that a guard an app defines
    is asked on a path its run takes, that an app said here to click nothing
    presses nothing in its run, and that no broad click is left unguarded.
    When an app asks for a document through Playwright's own client, which
    carries the browser's cookies, each redirect is checked with the same
    guard before it is followed, one step at a time,
    and an address asked for a second time follows none
    (`core/tests/test_no_request_follows_a_redirect_off_the_allowlist.py`).
    Target's headless fallback print asks the same guard about each request
    its browser holds before sending, each redirect hop included, leaves
    that browser no address for any host but Target's, and prints nothing
    once the page has left Target
    (`core/tests/test_headless_render_keeps_to_the_provider.py`).
- **Every browser starts inside its sandbox.** A browser an app starts
  itself goes through the core, which always asks for Chromium's sandbox,
  refuses any setting that would turn it off, takes no switch it has not
  been told keeps the sandbox whole, and starts nothing when the sandbox
  cannot start (`core/tests/test_every_browser_starts_in_its_sandbox.py`).
- **You sign in, not the tool.** The tools attach to a browser *you* logged into
  (via Chrome DevTools Protocol). They never handle your password or 2FA.
- **Local only.** The browser's debugging port and the GUI both listen on
  `127.0.0.1` (localhost), nothing is exposed to your network. Note that while
  the signed-in browser is open, any program running **on your own machine**
  could attach to that debugging port, so close the browser window when you're
  done downloading. The panel answers only a request its own page sent to
  `127.0.0.1` or `localhost`, so another website you have open cannot drive
  it, not even one that points a name of its own at your computer, and no
  other site may show the panel inside a page of its own. A link opened
  from an email, a chat or a PDF can open the panel, never start a run.
  Every answer it makes tells the browser to take it for exactly the kind
  of file it says it is, and to keep no copy of a page, a record or a
  download, and its page runs only its own script, named by its hash.
- **Spreadsheet text stays text.** Item names, store and merchant names and
  document titles are chosen by other people, and a spreadsheet takes a cell
  that starts with =, +, - or @ as a formula. The CSV files every app keeps
  beside its PDFs and both spreadsheet tools write such text with a single
  quote in front, or as an Excel text cell, so a spreadsheet opening one
  takes it as text, and an app reading its own files back takes that quote
  off again.
  The rule is `core/paperpull_core/sheets.py`, and a repo-wide test
  (`core/tests/test_sheets.py`) checks that every CSV reader and writer goes
  through it.
- **Delete-safe.** A sticky `downloaded_ok` marker means deleting the PDFs after
  you import them elsewhere will not cause re-downloads.

## If something may have been exposed

If your computer, its disk, a backup of the downloaders' folders or a copy
of a browser profile folder may be in someone else's hands, do these in
order. PaperPull Server has steps of its own, see
[SECURITY-SERVER.md](SECURITY-SERVER.md).

1. **PaperPull's own panel** keeps no sign-in on the desktop, and answers
   only on this computer, so there is nothing to end there.
2. **End the sign-ins at the providers.** Each provider's folder holds a
   browser profile folder with its live sign-in, `browser-profile` or a
   name ending in `-browser-profile`, and a copy of it works wherever it
   is. Close every sign-in browser, then delete those folders, which signs
   this computer out of every provider. A copy made
   before still works until each provider ends it. So sign in at each
   provider's own website from a device you trust, sign out every other
   device or session where it offers that, and change the password there.
3. **Take the newest release** from the
   [releases page](https://github.com/rheeloaded/paperpull/releases), or
   let the Store update it.

**How security fixes are announced.** Every release that fixes a security
problem says so under Security in [CHANGELOG.md](CHANGELOG.md) and in its
notes on the [releases page](https://github.com/rheeloaded/paperpull/releases).
To hear of every release, watch the repository on GitHub and choose
Releases, under Watch and then Custom.

## Reporting

This is a personal-use project with no warranty. If you find a security issue,
write to support@paperpull.net so it can be fixed before it is public, or open
an issue if it is not sensitive. Either way, never include real credentials,
account numbers or downloaded documents.
