# Coinbase statements and tax documents

Downloads your Coinbase monthly account statements and your tax documents
as PDFs, from a browser where you sign in yourself. Passwords and
verification codes are never handled by the downloader. Contributed by
[@JasperDale19](https://github.com/JasperDale19).

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull coinbase diagnose`, then `paperpull coinbase pilot`.
5. Check the downloaded documents before using `paperpull coinbase all`.

The sign-in browser uses port 9286, as `config.example.json` says. Existing
download history is retained in the provider's local state files. Deleting a
downloaded file does not reset that history.

## What it saves

Both pages are on `accounts.coinbase.com`, and the app opens each by its
address.

- **Monthly statements.** The Statements page lists one statement for each
  complete month back to the account's first. Each is saved by pressing its
  row's own PDF button once, on a page loaded afresh for it, and the
  download is taken only from Coinbase's statements host. The saved PDF has
  to name its own month more plainly than the month before or after, or it
  is not filed under that month. The "Last 30 days" row is not a statement
  and is skipped.
- **Tax documents.** The 1099-DA and the other tax forms for every year since
  the account's first transaction, and the pregenerated gain and loss PDF
  reports, read from the list calls the Taxes page makes and fetched from
  Coinbase's tax forms host. Nothing is pressed there, so the page's own
  mark-read and mark-downloaded calls never happen. Each is kept under its
  own id from that list.

- **Coinbase One Card statements.** The Statements page's Credit Card tab
  lists one statement for each month the card has closed. The app presses
  that tab, reads the list the page itself asks Coinbase for, and needs the
  rows it shows to match that list exactly. Each statement is saved by
  pressing its row's own PDF button once, on a page loaded afresh for it.
  The page is then handed the statement's own address, and the browser
  goes there itself. The app takes it only from Coinbase's card statement
  host (statements.cardless.com) and only when that address carries the
  statement's closing date, fetches that exact address, and keeps it only
  as a PDF that says Coinbase One Card and prints that closing date. It is
  named `<closing date> Coinbase One Card Statement.pdf`. A popup, a
  download, the browser going anywhere else, or an answer naming another
  statement or another date stops the run. An account whose Statements
  page shows no Credit Card tab has no card statements listed. A card list
  that cannot be read whole, or that names more than one card account,
  leaves only the card statements. The monthly statements and tax
  documents are still taken, and the run ends as one that did not finish,
  so the card statements are asked for again on the next run.

The statements list is called whole only when it reaches back to the month
of the account's first transaction, and a tax list that names another year
or has a page this does not read stops the listing too.

Never touched are the custom statement generator, the tax report generator,
the card's payments and settings, and anything that trades, sends, stakes or
changes a setting. The app never asks Coinbase's card list or a statement's
address for itself, it only hears what the page asks. The statement's id,
the card account's id, the signed address and the amounts are never logged
or kept.

## Validation status

Mapped against a signed-in retail account on 2026-10-09. A full run there
saved 66 statements and 2 tax documents, every one a valid PDF. Automated
tests cover the guard, the hosts, the statement rows and their months, the
tax lists, the press of a statement's PDF button and what it brings, and
filing a statement only under its own month.

Coinbase One Card statements ran live on the same account on 2026-10-15.
Discover listed the Credit Card tab's 13 statements, October 2025 to
October 2026, beside the account statements, Pilot took the first and Run
All the rest, every one a PDF naming "Coinbase One Card" and its closing
date, with the account statements and tax documents untouched. The run
showed two things the survey had not. On a repeat visit the page gets its
list and a statement's address through its GET persisted query alone, with
no POST after it, so both are heard, and the tab's move to the statement's
address evicts that answer's body before it can be read, so the address is
then read from where the tab landed, held to the row's date and to the
request that named the row's statement. Automated tests cover the card
list heard and matched to its rows, the press of a row's PDF button, the
address and the PDF checked, every stop, and that no id or signed address
is logged or kept.
