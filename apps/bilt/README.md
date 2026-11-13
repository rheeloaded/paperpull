# Bilt Card statements

Downloads the monthly statements of the Bilt Card 2.0, the card Cardless
services, from the Bilt wallet at `www.bilt.com/wallet`, as PDFs. This
reads from a browser where you sign in yourself, on the port named in
`config.json` (see `config.example.json`, port 9297). Passwords and
verification codes are never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Validation status

**Run live on one account on 2026-10-15.** Discover listed the wallet's one
Bilt Blue Card and its eight statements, October 06, 2026 back to March 06,
2026. Pilot took the newest and Run All the other seven, every one a PDF
that printed its own statement date and the card's last four, and Verify
found eight index rows with no problem. Three loads of the wallet in that
session (Discover, Pilot, Run All) listed the same eight ids, so a
statement's id held from one load to the next. The run showed three things
past the survey it was built from.

- The wallet shows the card under a "View balance summary" button. That
  opens a sheet with "View statements", which opens a second sheet with one
  button per statement, "Download statement for October 06, 2026". The
  card's label on the wallet is split across elements, the name, the masked
  number and the card's own "View" button, and the "View statements"
  control's accessible name carries the name of an icon nested in it, so
  both are read by their own text.
- Opening the list makes the page ask Bilt's API for the card's
  statements, and the app hears that answer. It never asks the API itself.
- A statement's button makes the page ask for that statement's details and
  then open a new tab at `statements.cardless.com` holding the PDF, at a
  signed address. The address carries the statement's own date in its
  path and exactly the query keys Expires, Signature and Key-Pair-Id. No
  browser download begins. The tab is closed once the PDF is taken.

Two things are still unseen, how long Bilt keeps an idle session and
whether a statement's id holds across a fresh sign-in.

Statements of the earlier Bilt card issued by Wells Fargo, before February
2026, are not in the Bilt wallet. They are Wells Fargo's, and the
[`wellsfargo`](../wellsfargo) app reads Wells Fargo.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page. The first time you open
   PaperPull it shows its terms and asks which folder your documents go in,
   then shows the same list by itself. Click **Bilt**, then **Continue**,
   then **Set up**. Back on Accounts, click **Bilt** to open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Unlike the one on the provider's page, it starts no download once
   you are signed in. Your own Edge or Chrome opens with a separate profile.
   Sign in to your Bilt account yourself, open **Wallet**, make sure the
   wallet shows your Bilt Card, and leave the window open.
4. Back in Get help, click **Make the report**. This support report opens
   the wallet by its address and writes
   `Diagnostics\diagnose-documents.json` in the Bilt folder. It downloads
   nothing, clicks nothing, takes no screenshot, and writes any word that is
   not on PaperPull's fixed list as its shape.
5. Once the report is done, click **Back to Bilt**, then **Try the newest
   few first**. It saves the newest statement and stops. Open the PDF and
   check it is the statement of the date in its name.
6. Open the Diagnostics file in Notepad and look through it. It should hold
   counts and the shape of each address, no values. If anything in it looks
   personal, delete that line.
7. Attach it to a new
   [provider issue](https://github.com/rheeloaded/paperpull/issues/new/choose)
   titled "Bilt Card", with a sentence saying whether step 5 saved the
   right statement.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it, with
no text from your account in it. Attach it to the issue the same way.

## Setup and use, for a checkout

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Open Wallet and
   leave it showing your Bilt Card. Leave the window open.
4. Run `paperpull bilt diagnose`, then `paperpull bilt pilot` (one statement).
5. Check the downloaded statement before using `paperpull bilt all`.

## How it works

The app opens the wallet by its address and presses only three things:
the card's "View balance summary", then "View statements", then one
statement's own button. It never moves the wallet's card carousel, so a
wallet left showing another card, or showing more than one Bilt Card, stops
the list. The card's balance summary button, its card label and its
"Recent activity" link have to belong to the one card.

The list of statements is the answer the page itself gets from Bilt when
"View statements" opens, heard as it arrives. That answer has to be one
answer, for the card the wallet shows, with its count equal to its list and
no statement or date twice, and the sheet has to show exactly its dates,
one button each, read twice alike. The answer the run saw held nothing but
its list and its count, so an answer that holds anything more (a sign of
more statements, a cursor or a total) stops the list, and so does a sheet
that shows a control for more or older statements. Anything else stops
the list rather than being called whole.

Before each statement the wallet is loaded again and the list read again,
whole, and exactly one statement there must carry the recorded id and date.
Only then is that statement's button pressed. The statement is kept only
when exactly one tab opened, on `statements.cardless.com` at the PDF
address of that statement's date, the page's own details answer named that
statement, no browser download began, and no other tab opened. The tab is
closed before anything is saved. The PDF has to print the statement's date,
and when it prints masked card numbers, the card's last four has to be
among them (a statement may also mask the account a payment came from).
A statement whose button is turned off on the page is left for the next
run and the run goes on. Anything else unexpected stops the run.

If Bilt answers as signed out, the run stops and keeps what it saved. Sign
in again and run Resume. A signed-out visit to the wallet stays at its own
address and draws Bilt's sign-in there ("Complete login to continue", "Log
in or sign up" and the "Sign up / Log in" button), and that is read as
signed out too. A wallet that shows neither the sign-in nor one Bilt Card
stops the list instead.

Files are named `YYYY-MM-DD Bilt Card Statement.pdf`. Only when that name
is already taken does the file add six letters that tell it apart. No card
number or statement id is ever in a file name. A Download again of a
statement whose file is still there saves a second copy beside it, and a
PDF that is the very file of another statement already saved is never
kept.

Never touched are Pay card, Pay with points, Make payment, Transfer a
balance, Lock card, Manage card, Authorized users, Add, Refer a friend,
Rewards, Neighborhood, the concierge chat, your profile and the wallet's
Previous and Next card. Your card id, statement ids, the card's last four,
your name, your balances and your recent activity are kept out of every
log, the index and every diagnostic file. The card id and statement ids
are kept only in the app's own discovery and progress records, to find the
statement again.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only and need no browser.
