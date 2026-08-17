# Changelog

All notable changes to PaperPull are recorded here. Versioning follows
[Semantic Versioning](https://semver.org):

- **PATCH** — bug fixes, or repairing an app after a provider changes its site
- **MINOR** — a new app, or a cross-app feature
- **MAJOR** — breaking changes (repo layout, config format, removing an app)

## [0.4.1] — 2026-08-16

### Fixed
- **Gap** — in-store purchases are now separated from online orders. Gap's
  history page mixes the two; they were all being typed "Online" and filed in
  `Online\`. There is now an `In-Store\` folder (matching the Target and
  Walmart apps), online orders record the Gap Inc. brand that shipped them,
  in-store purchases record the store, and `--online` / `--instore` run one
  kind. Also fixes card-boundary detection: card text was bounded by length,
  so on an account whose cards are sparse the walk captured the whole list and
  every purchase inherited the first card's date. A card now ends at the first
  sibling order id.

### Changed
- **Gap** gained `run_online.bat` / `run_instore.bat`, matching Target and
  Walmart.
- **Amazon** drops the same dead invoice branch as Gap: `_handle_no_receipt`
  was never called, so the `Invoices\` folder and the `include_invoices` knob
  it depended on could never be reached. What Amazon saves is unchanged — its
  printable order summary is captured as the receipt, as it always was.
- **Every app** now creates only the document folders it can actually fill.
  Each app was cloned from the nearest existing one and inherited that app's
  whole folder list, so installs grew permanently-empty folders — `Insurance
  Documents` (real only for USAA, which is also an insurer), `Other Documents`
  (never a configurable document type), and `Invoices` (reachable only in the
  Target and Walmart apps). Routing is unchanged and now creates a folder on
  demand, so a category that is reachable but rare still gets its folder the
  moment a document lands there. Nothing that holds documents is affected.

## [0.4.0] — 2026-08-16

### Added
- **Gap Inc.** — order receipts (13th provider). One Gap login covers Gap, Old
  Navy, Banana Republic, Athleta and Gap Factory, and a single order history
  holds orders from all of them; the brand is recorded per order. The order
  history lazy-loads on scroll rather than paginating by year, so discovery is a
  single scrolled pass over everything Gap still exposes (about the last 13
  months). Gap ships no printable invoice and no print stylesheet, so each
  order's own details page is captured: the app waits for the page to load its
  data, hides everything outside the purchase-summary block (a display-only
  change to the local page), and renders the result with `printToPDF` — a
  receipt with the purchase header, line items and charge summary, and none of
  the site navigation.

## [0.3.1] — 2026-08-16

### Security
- **GUI control panel** now refuses any request whose `Origin`/`Referer` host is
  not localhost, closing a cross-site "trigger a run" vector on the command API
  (`/api/apps`, `/api/run`). The server already binds to `127.0.0.1` only and
  has no CORS; `SECURITY.md` now documents the localhost/CDP posture (close the
  signed-in browser when you're done — while it is open, any local process could
  attach to its debugging port).

## [0.3.0] — 2026-08-16

### Added
- **Verizon (Fios)** — Fios / Home Internet bill statements (10th provider).
  Uses your installed Microsoft Edge (T-Mobile-style bot protection blocks the
  bundled Chromium) and captures downloads via a controlled directory over CDP.
- **T-Mobile** — monthly bill statements (11th provider). Reads the bill-history
  page and downloads each period's detailed-bill PDF via a real download event.
- **Target RedCard / Target Circle Card** — monthly billing statements (12th
  provider). The RedCard credit account is serviced by TD Bank USA; reads the
  statements table (per-year switcher) at mytargetcirclecard.target.com and
  downloads each row's statement PDF via a real download event.

## [0.1.0] — 2026-08-15

First tagged release.

### Apps (9 providers)
- **Amazon** — order invoices, full order history
- **American Express** — statements + year-end summary
- **Dominion Energy (VA)** — billing statements
- **Navy Federal Credit Union** — account statements
- **Robinhood** — account statements + tax documents
- **Target** — receipts
- **USAA** — statements
- **Walmart** — receipts
- **Wealthfront** — statements + tax documents

### Features
- Read-only, connect-to-your-browser design — you sign in yourself; the tool
  never handles credentials or bypasses 2FA
- Delete-safe skip — deleting PDFs after importing them elsewhere never causes
  a re-download
- Account-holder ("owner") tagging: a first-run prompt plus an "Account Holder"
  column in the index CSV
- Multi-account support via `--config`
- Local FastAPI **control-panel GUI** that drives every app
