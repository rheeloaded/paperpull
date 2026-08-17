# Adding a provider

No one person has accounts everywhere — so PaperPull grows when people add the
providers *they* use. This guide walks you through building a new downloader
app, using the same pattern all 12 existing apps share. Budget a few focused
hours; most of the work is figuring out how one specific site lays out its
statements.

If you just want a provider to *exist* but can't build it yourself, open a
[provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
instead — someone with that account may pick it up.

---

## The three non-negotiables

These keep PaperPull safe to run against real financial accounts. A PR that
breaks any of them can't be merged.

1. **Read-only, always.** Your app may only navigate, read a document list, and
   download PDFs the provider already generated. It must **never** click a
   control that pays, transfers, redeems, enrolls, disputes, or changes any
   setting. Every clickable control is gated by two regexes in your
   `*_site.py`: a blocklist (`FORBIDDEN_CONTROL_RE`) *and* a document allowlist
   (`SAFE_DOC_CONTROL_RE`). A control must pass **both**. There is no code path
   anywhere that submits a form or confirms a dialog — keep it that way.
2. **Never handle credentials.** The user signs in themselves in a real browser
   window; your app *attaches* to that already-signed-in session over the Chrome
   DevTools Protocol. Your code never sees a password, never types into a login
   field, and never touches 2FA.
3. **Never commit private data.** No real `config.json`, no `*-browser-profile/`,
   no downloaded PDFs, no logs/CSVs/state. These are all gitignored — run
   `git status` before every commit and confirm only source is staged. See
   [SECURITY.md](../SECURITY.md).

---

## How an app is built (60-second tour)

Each app is a generic engine plus **one** provider-specific file:

- `*_docs.py` / `*_receipts.py` — the engine: discovery, delete-safe state, PDF
  validation, folders, the CLI (`--login/--discover/--pilot/--all/--resume/
  --verify/--diagnose`). **You rarely touch this.**
- `*_site.py` — **everything provider-specific**: URLs, selectors, how to reach
  the documents, how to list them, how to download one, plus the safety guards.
  **This is the file you write.**
- `storage.py`, `models.py`, `doc_types.py`, `receipt_pdf.py` — shared helpers
  you inherit unchanged (filenames, CSV index, classification, PDF checks).
- `config.json` — per-install: output folder, browser-profile folder, and a
  unique CDP port. (`config.example.json` is the tracked template.)
- `login.bat` launches a browser with `--remote-debugging-port=<N>`; the app
  connects with `chromium.connect_over_cdp("http://localhost:<N>")`.

So your job is really to answer three questions for your provider, inside
`*_site.py`:

> **1. Where are the documents?** (navigate there)
> **2. What documents exist?** (read the list — dates + titles)
> **3. How do I download one?** (click/fetch → save a PDF)

---

## Which provider is a good first build?

Some sites are much friendlier than others. If this is your first PaperPull app,
pick one that looks **easy**, and save the hard ones for later.

**Easy (great first build)** — a portal that:
- keeps you signed in across normal navigation (`page.goto` works — a
  server-side cookie session), **and**
- lists statements in a plain HTML table or list, **and**
- has a direct "Download PDF" link that fires a real browser download, **and**
- doesn't block the bundled Chromium.

Closest templates: **`redcard`**, **`tmobile`**, **`dominion`**. If your
provider looks like these, you can likely be done in an afternoon.

**Medium** — statements split across a year/period dropdown or pagination;
multiple document types to classify; a download that opens a blob in a new tab
you have to `fetch()` (see `navyfederal`).

**Hard (not a first project)** — bot detection that blocks Chromium (needs real
Edge — `walmart`, `verizon`); an in-memory SPA session where `page.goto` logs
you out (`amex`); print-only receipts with no download button, captured via
`printToPDF` (`walmart`, `target`); or a portal whose session expires fast and
silently (`redcard`).

Not sure which bucket yours is in? Sign in, poke around the statements page for
ten minutes, and check: does refreshing the URL keep you logged in, and does a
statement have a real download link? Two yeses = easy.

## Step by step

### 1. Clone the closest existing app

Pick the app most like your provider and copy its folder to `apps/<yourslug>/`:

- **Receipts** (retailers): clone `amazon` or `target`.
- **Statements** (banks, brokerages, cards, utilities, telecoms): clone `amex`,
  `robinhood`, `dominion`, or `redcard`.

Rename the two entry files to `<yourslug>_docs.py` / `<yourslug>_site.py` and do
a find-and-replace of the old slug/name (watch for the provider's **full** name,
e.g. "American Express" as well as "Amex" — the token substitution misses it).

### 2. Pick a free CDP port + set config

Each app uses its own debugging port so several signed-in browsers can be open
at once. Taken so far: **9222–9233**. Use the **next free port (9234+)** in your
`config.example.json` and local `config.json`, and point `output_dir` /
`profile_dir` at this app's folder.

### 3. Sign in and explore the live DOM

This is where the real work is. Run `login.bat`, sign in yourself, open your
statements page, and **leave the browser open**. Then attach and inspect — the
download mechanism is the key unknown every time. Write a throwaway probe (see
any app's history) or use `--diagnose`, and answer:

- What URL holds the document list? Does the session **survive `page.goto`**
  (server-side cookie session) or only survive **click-navigation** (in-memory
  SPA token, like Amex)?
- How is the list structured — a table? cards? a year/period dropdown?
  pagination or "load more"?
- **How does a download actually happen?** This varies a lot (see Tips below).

### 4. Implement the site layer

Rewrite `*_site.py` to answer the three questions. At minimum the engine expects
these (names vary slightly by base app — match whatever your cloned `*_docs.py`
calls):

| Function | Does |
|---|---|
| `goto_documents(page)` | Navigate to the documents area; return `True` if it loaded |
| `collect_download_docs(page)` (or `collect_documents`) | Return a list of docs, each with an ISO `date_text` and a `title` |
| `download_document(page, …, out_path)` (or `download_bill`) | Download one doc's PDF to `out_path`, return `True`/`False` |
| `looks_signed_out(page)` / `detect_security_challenge(page)` | Session/challenge detection (mostly inherited) |
| `is_safe_control(name)` + `FORBIDDEN_CONTROL_RE` / `SAFE_DOC_CONTROL_RE` | The read-only guard — **tune the blocklist to your provider** |
| `parse_date` / `parse_period_date` | Date parsing (inherited; extend the format list if your dates are unusual) |

### 5. Tune the read-only guard

Add provider-specific dangerous verbs to `FORBIDDEN_CONTROL_RE` (e.g. a card
portal needs `redeem`, `balance transfer`, `cash advance`; a utility needs
`autopay`, `budget billing`). The tests in `tests/test_doc_types.py` assert a
long list of money/account controls are refused — keep them green.

### 6. Test it

From the app folder, with its venv active:

```
python <slug>_docs.py --discover     # lists what it found
python <slug>_docs.py --pilot        # downloads the newest few, then stops
python -m pytest tests               # keep tests green
```

Verify the pilot PDFs open and look right, then re-run `--pilot` and confirm it
reports **"already downloaded — skipping"** (delete-safe works).

### 7. Scrub and open a PR

`git status` — only source should be staged (no profile/config/PDFs/state). Add
your provider to [PROVIDERS.md](../PROVIDERS.md), fill in the PR checklist, and
open it. See [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Tips (hard-won across 13 apps)

- **Download mechanisms vary — identify yours first.** Seen so far: a real
  browser **download event** (`page.expect_download`, most common); an inline
  **blob-in-new-tab** you `fetch()` from the page context (Navy Federal); CDP
  **`Page.printToPDF`** when the receipt is a print-only page with no download
  button (Walmart/Target); and a browser-managed download dir when attached to a
  user-launched browser (Verizon).
- **Bot detection?** If the site blocks the bundled Playwright Chromium (a WAF
  page, an endless "are you human" loop), launch **real Microsoft Edge / Chrome**
  instead — see `walmart`/`verizon` `cmd_open_browser`. A branded browser passes
  where the Playwright build doesn't.
- **SPA vs server session.** If `page.goto` logs you out, the session lives in an
  in-memory token — navigate by **clicking** the app's own links and reuse the
  signed-in tab (see `amex`). If `goto` is fine, use URLs (most providers).
- **Short sessions.** Some bank portals expire fast and the SPA keeps showing a
  cached page while download clicks silently no-op. Detect it (a hard reload
  bounces to the login URL) and report it so `--resume` retries after re-login
  (see `redcard`).
- **Pagination / history.** Statements are often split by year/period behind a
  dropdown or "load more" — walk all of them during discovery.
- **Broken `aria-label`s happen.** Derive dates from the visible row text, not a
  label the site failed to interpolate (see `redcard`).

Read the `*_site.py` of the app closest to yours — it's the best template, and
each one's top comment documents that provider's quirks.
