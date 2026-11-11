# TreasuryDirect (savings bonds and Treasuries)

**Run live on one account, 1099s unconfirmed.** TreasuryDirect's signed-in
pages were surveyed read-only on 2026-10-13, by clicking their own links,
and the app then ran on that account. Discover listed 3 documents, Pilot
saved 1, Run All saved the other 2, and every PDF opened. That account had
no taxable transactions, so the tax pages have never been seen. A taxable
year is listed for you to save by hand, and its link is never pressed.

TreasuryDirect has no PDFs. Every page is a web page, so this app saves the
pages themselves as PDFs, into `Statements\`.

| Page | File name | How often |
|---|---|---|
| Current Holdings (the summary) | `2026-10-13 TreasuryDirect Current Holdings.pdf` | one per day you run it |
| History, Security History | `2026-10-13 TreasuryDirect Security History.pdf` | one per day you run it |
| History, Payment History | `2026-10-13 TreasuryDirect Payment History.pdf` | one per day you run it |
| ManageDirect, Manage My Taxes, a year with a 1099 | not saved yet, listed once under Needs Manual Review for you to print yourself | once per tax year |

A year that ManageDirect lists as "(No taxable transactions)" has nothing
to save, and is skipped.

One sign-in can hold several accounts. Each document is kept under the
account it was listed on, known by a digest of its account number and
never by the number, and is saved only while your tab shows that
account. Otherwise it is left under Needs Manual Review. A second
account's file of the same day ends in the first six letters of that
digest. If your sign-in holds several accounts and its pages show no
account number, the run stops rather than guess.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## How it works

TreasuryDirect ends your session if a page is opened any way other than by
its own links, the browser's Back, Forward and Refresh buttons included.
So the app never opens an address. It works in the tab you signed in with,
and moves only by pressing the page's own links, one at a time, the
Current Holdings, ManageDirect and History tabs, and Security History and
Payment History. Each press is checked twice, by the link's words and its
exact destination on www.treasurydirect.gov, and by the page it lands on,
and goes through PaperPull's press guard, which refuses a link anything is
drawn over. Each page is then turned into a PDF with everything active
taken out of it, its scripts, forms, frames and link addresses, and is
drawn with JavaScript off, without your cookies and without the network.
A PDF is kept only when its own text names the page it was meant to be.

The app never presses BuyDirect, Gift Box, Logoff, Return To Account
Listing, Account Info, the Investor InBox (opening a message marks it
read), or any ManageDirect link that changes your account, such as
passwords, security questions, bank information, registrations,
reinvestments, transfers, redemptions, rights and linked accounts. No form
is ever submitted, so no Submit, Cancel or Delete is ever pressed, and the
Security History and Payment History pages are saved as they first show.

If TreasuryDirect signs you out ("TreasuryDirect is unavailable.", or the
sign-in page), or asks for a passcode or a security answer, the run stops,
keeps what it saved, and asks you to deal with it in the browser yourself
and then Resume. Your account number, name, the session's id and
confirmation numbers are kept out of every log and diagnostic file. They
stay in the saved PDFs, which are your documents.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page. The first time you open
   PaperPull it shows its terms and asks which folder your documents go in,
   then shows the same list by itself. Click **TreasuryDirect**, then
   **Continue**, then **Set up**. Back on Accounts, click **TreasuryDirect**
   to open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Unlike the one on the provider's page, it starts no download once
   you are signed in. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, with ID.me or TreasuryDirect's own sign-in, and leave
   the window on your account. Do not use the browser's Back button. Then
   click **Close** to leave Get help.
4. Click **Try the newest few first**. It saves the newest document and
   stops. Say whether a PDF landed in `Statements\` and whether it looks
   right.
5. If you have a tax year with a 1099 (ManageDirect, Manage My Taxes, a year
   **without** "(No taxable transactions)"), open that year's page in the
   browser yourself. Then in PaperPull click **Back to TreasuryDirect**,
   then **More**, then **Get help**, and click **Make the report**. This
   support report writes
   `Diagnostics\diagnose-documents.json` about the page your tab is on. It
   presses nothing, takes no screenshot, and writes any word that is not on
   PaperPull's fixed list as its shape. Do the same on the 1099 itself.
6. Open each file in Notepad and look through it. If anything in it looks
   personal, delete that line. Attach them to an issue titled
   "TreasuryDirect" on [GitHub](https://github.com/rheeloaded/paperpull/issues).

**If a run stops early, send the file it wrote.** Every failed run leaves
a `failure-*.json` in the `Diagnostics` folder and prints where it put it,
with counts and states and no text from your account in it.

## Setup, for a checkout

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat`, sign in yourself, and leave the window
   on your account.
4. Run `paperpull treasurydirect pilot` (one document), check it, then
   `paperpull treasurydirect all`.

## Validation status

Surveyed 2026-10-13 (read-only, clicks only) on one account with savings
bonds and no taxable transactions. It confirmed the signed-in address
and its page names, the top tabs, ManageDirect's Manage My Taxes list,
History and its Security History and Payment History pages, Current
Holdings, and what an ended session looks like. Then the app ran live on
the same account, Discover 3, Pilot 1, Run All 2, every PDF valid. These
have not been seen yet.

- A tax year with a 1099. The year is assumed to be a link "Year 2025",
  which is listed but never pressed. Its page, any "View your 1099 for tax
  year 2025" link and the way back must be surveyed before the app saves a
  1099 itself.
- Linked accounts, which are never opened. Only the account your tab is
  on is read.
- A sign-in of several accounts. Each document is bound to its account
  by the number its pages show, which is checked with made-up pages only.
- The Investor InBox, which is not read.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only and need no browser.
