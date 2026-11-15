# First Horizon Bank statements

Downloads the monthly statements of your First Horizon Bank accounts from
digital banking, `digital.firsthorizon.com`, as PDFs, about two years of
them. This reads from a browser where you sign in yourself, with your
password and one-time code, on the port named in `config.json` (see
`config.example.json`, port 9289). Passwords and verification codes are
never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull firsthorizon diagnose`, then `paperpull firsthorizon pilot` (one statement).
5. Check the downloaded statement before using `paperpull firsthorizon all`.

First Horizon signs you out after ten minutes without activity, so start
the run soon after signing in.

## How it works

The app opens the Statements page by its address and presses only two
things: an account's panel, to open it (never to close it), and one
statement's own "Download PDF". Every account panel the page shows is
read, and a closed one is pressed open. A panel the page hides, or draws
only after the list is read, stops the list rather than being left out,
so a hidden account is not listed. The list of an account's statements is
the answer the page itself gets from the bank when the panel opens, heard
as it arrives. The app asks the bank nothing of its own except whether the
session is signed in. Before each statement the page is loaded again and
the account found again by that answer, opening its product's panels only
until the account is found. The button is pressed only when one account,
exactly one statement and one card match what was recorded. A page that
stops the list on the way, as a panel turned off, stops the run.
The PDF is the download the bank's own button makes, kept only when it
comes from that statement's own address and is a PDF. A list the app
cannot read stops rather than being called whole.

If the bank answers as signed out, or shows its session-timeout warning,
the run stops and keeps what it saved. Sign in again and run Resume. When
the bank refuses one statement, the Statements page is opened again and
the app asks the bank once more whether the session is signed in. If it
is not, the run stops the same way. If the page does not open, times out
or shows no account, or the bank's check answers with a server's error,
that says nothing about your sign-in, so the run stops
there with nothing recorded against that statement, and the panel offers a
run that reads the list first, which takes it. If it is signed in, that
one statement is counted as failed with nothing saved, the run goes on to
the others, and the next run tries it again. Its Download PDF is never
pressed twice. A run also stops on its own eight minutes after it first
checks the session, before the next statement, so the ten-minute session
never ends mid-download. Sign in again for a fresh session and run Resume.

Files are named `YYYY-MM-DD First Horizon Bank Statement.pdf`. Only when
that name is already taken, as by two accounts' statements of one date,
does the second file add six letters that tell it apart. No account or
document number is ever in a file name.

## Validation status

Built from a survey of a signed-in account on 2026-10-12, which listed one
checking account with 24 statements, then run on it the same day: Discover
listed 24, Pilot saved one, and Run All saved the other 23 and left no tab
open. Not yet seen:

- More than one account on one sign-in.
- Two statements of one account on one date, which stop the list.
- One statement id under two dates, in one listing or from one listing to
  the next, which also stops the list, leaving the saved record as it was.
- Tax forms. They are online only once the account holder enrolls in
  online tax statements, a decision this app never makes for you. Until
  then there are none to download.

Never touched are payments, transfers, Zelle, Enroll, Manage Statement
Delivery, Account Options, the session-timeout dialog and Log Out. The
app never calls the site's keepalive and never presses View Online. Your account ids, nicknames, account
names, masked numbers and the bank's document ids are kept out of every
log, the index and every diagnostic file, and files and the index name an
account only by its product, such as "Express Checking". The account id is
kept only in the app's own discovery and progress records, to find the
statement again.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only and need no browser.
