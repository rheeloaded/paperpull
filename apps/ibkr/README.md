# Interactive Brokers statements

Downloads the monthly Activity Statement PDFs from Interactive Brokers' Client
Portal, from a browser where you sign in yourself. Passwords and the second
factor, which Interactive Brokers sends to your phone, are never handled by the
downloader.

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat`, sign in yourself, approve the sign-in on
   your phone, and leave the window open.
4. Run `paperpull ibkr diagnose`, then `paperpull ibkr pilot`.
5. Check the downloaded statements before using `paperpull ibkr all`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## What it downloads

The monthly Activity Statement, filed under the last day of its month, for the
account the Statements page shows. The Statements page also offers tax
documents, trade confirmations, flex queries and third-party reports. None of
those are read, so no folder is made for them. They can be added in a later
change on the same page.

## Validation status

Run against one real account (an individual brokerage account at Interactive
Brokers LLC) on 2026-10-10: discovery listed 61 monthly statements, September
2021 to September 2026, a pilot saved 5 of 5, and a second pilot downloaded
nothing. A full run saved 60 of 61; the one that did not save had a single
intermittent "no download", and a supervised retry saved it. Each PDF's own
heading names the month in its file name. The `.com`, `.co.uk` and `.ie` hosts
have been seen, so an account sent to another regional domain stops at the
sign-in check, with a message naming the domain, until it is added to
`ALLOWED_HOSTS` in `ibkr_site.py`. Automated tests cover the month parsing, the
control guard, the host check, and that both pressed controls go through the
guard.

## How it reads the site

Sign-in is at `www.interactivebrokers.com/sso/Login`, which sends the browser
to the domain of its region. The Statements page is a page of the Account
Management app, `/AccountManagement/AmAuthentication?action=RM_STATEMENTS`, and
is reached on the host the person signed in on. Its Default Statements list has
one row per kind of statement, each with an Info link and a Run link. The Run
link of the row named Activity Statement opens a dialog with a Period select and
a Date select. With Period set to Monthly the Date select lists every month the
account has, and that list is what discovery reads, so nothing is computed from
the account's age.

Each statement is the dialog's own Download PDF button, pressed once with the
month chosen. The browser saves into `.ibkr-downloads`, a staging folder in the
output folder, given to the browser as a full path, and the file the download
event names is moved into place under the app's name. The file's own name says
which month it is for (`<account>_<YYYYMM>_<YYYYMM>.pdf`), and a file that says
another month than the one asked for is not taken.

Nothing is requested from the statement address directly. A plain request made
from outside the page's own client is refused for lack of a session value the
page adds, and it ends the session, so the page's own button is the only way
this asks for a statement.

The portal's session is short. A session that has ended lands on a page that
says so, and the app reports it as signed out, so that Resume carries on after
you sign in again.

## Nothing is pressed under something else

No press is ever forced. The Run link and the Download PDF button are brought to
the middle of the window first and pressed only when they are the thing on top
at the point the press lands. When a banner or an offer sits over one, nothing
is pressed, the run stops and says what is over it in words from PaperPull's
fixed list, and a failure file is written. A press that brings no download at
all is not made again, and the run stops there as well. Close whatever covers it
in the browser window, then press Resume in the panel or run
`paperpull ibkr resume`.

Both pressed controls pass the guard with their own words, and the Run link is
also required to sit in the row named exactly Activity Statement, since the
same page has a delivery setting with a similar name that must never be pressed.
The page also has Deposit, Withdraw, Transfer Funds, Orders & Trades and Trade
controls, which the guard refuses.
