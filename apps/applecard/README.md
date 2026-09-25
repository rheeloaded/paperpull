# Apple Card and Savings document downloader

**Not yet tested against a real account.** This app was built without an
Apple Card or a Savings account, so that someone who holds them can test
it without writing code. Everything it believes about a signed-in
card.apple.com page is a guess, marked GUESS in `applecard_site.py`. It
runs, its guard is tested, and it is waiting on one recording from a
real account. The conversation is
[issue #52](https://github.com/rheeloaded/paperpull/issues/52).

Downloads your **Apple Card monthly statements, Savings monthly
statements and tax forms** (the 1099-INT a Savings account gets) as PDFs.
Read-only, delete-safe, part of [PaperPull](../../README.md).

- **Read-only.** Nothing is paid, scheduled, transferred, added to
  Savings or withdrawn from it. Daily Cash and Apple Cash are never
  touched, no charge is disputed, no card number is shown and no setting
  is changed. The guard in `applecard_site.py` refuses every control
  whose name says otherwise, and there is a test for each of them.
- **You sign in yourself.** No Apple Account, password or code is ever
  typed by this app or stored by it.
- **Nothing leaves your machine** except the pages Apple itself serves
  you.

## Help test it, no programming needed

The short version. The long version, written for somebody who has never
contributed to anything, is
[Testing a provider](../../docs/testing-a-provider.md).

1. Install PaperPull from the
   [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Apple Card**. Pick it in the App
   list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile
   at card.apple.com. Sign in yourself, approve the code on your iPhone or
   Mac, and leave the window open.
4. Click **more** under the buttons, then **Record**. Go back to the
   browser and click your way, the way you normally would, to

   - one **Apple Card statement**, as far as downloading its PDF,
   - one **Savings statement**, the same way, and
   - one **tax form**, a 1099-INT, if the site shows you one.

   Then come back and click **Stop recording**. It writes
   `Diagnostics\recording.json`, the path you actually took. One
   recording can hold all three trips. If you do not have Savings, or no
   tax form is listed, just record what you have.
5. Click **Diagnose** as well, in the same **more** menu. That writes
   `Diagnostics\diagnose-documents.json`, what the app itself sees on each
   of the three pages, which says what it got wrong. It downloads
   nothing, presses nothing but a Statements, Savings or Documents link,
   takes no screenshot, and masks any run of six or more digits.
6. Open each file in Notepad and read it through. It should hold page
   headings, the names of buttons and links, and the shape of the data
   the page loads, no values. The recording ends by printing anything
   worth a second look. If anything in either file looks personal,
   delete that line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach both files to
   [issue #52](https://github.com/rheeloaded/paperpull/issues/52) with a
   sentence about where you found each kind, and how far back the lists
   go. Do not attach a screenshot of a statement. Those carry your card
   and account numbers, and the recording deliberately does not.
8. When a new build is posted, click **Pilot** and say whether PDFs
   landed in `Statements\` and `Tax Documents\`, and whether the card and
   Savings statements came out with the right names.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps.

One recording is usually enough to write the first working build. Expect
a few Pilot runs after it, each with a word about what came out wrong,
which is the normal shape of it and not a sign anything went wrong.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to the issue the same
way. It is what keeps the rounds after the first one short, and it is
described in full on the
[Testing a provider](../../docs/testing-a-provider.md#if-a-run-fails-send-the-file-it-wrote)
page.

## What Record captures, and what it does not

It writes down each button and link you press, named the way you read
it, where the page moved to with everything after the `?` removed,
whether a new tab opened, and the name of any file that downloaded. It
keeps the addresses of Apple's own data requests and the shape of what
came back, the names of the fields and never their values, and the
structure of the page around each control, element kinds and counts
only.

It does not record anything you type. There is no keystroke listener in
it at all, so your Apple Account, password and code never reach it. It
reads no cookies, headers or browser storage, and takes no screenshot.
It refuses to start before you are signed in. The full list is on
[Testing a provider](../../docs/testing-a-provider.md#what-record-captures-exactly).

## What is known, and what is a guess

Known, from the requester and from what Apple says in public.

- **You sign in at card.apple.com** (#52), with your Apple Account and a
  code sent to one of your own devices.
- **Apple Card statements run for a calendar month**, so a statement
  named by its month closes on that month's last day, which is the date
  this app files it under.
- **Statements can be downloaded as PDFs on card.apple.com.** Apple also
  offers your transactions as a CSV or OFX export. Those are not
  statements, this app never wants them, and the guard refuses them.
- **Savings is managed from the Apple Card account** and has its own
  monthly statements, and a Savings account that earned interest gets a
  1099-INT each year.

A guess, marked GUESS in the code.

- The addresses of the card's statements, the Savings statements and the
  tax forms. If none of them is right the app starts at the overview and
  presses Statements, or Savings and then Statements, the way a person
  would.
- How a month is written next to its download button. A button whose row
  does not name exactly one month is left alone and counted, never filed
  under a neighbor's month.
- Where the 1099-INT lives, whether beside the Savings statements or on a
  page of its own.
- Whether a download is a file, a PDF in a new tab, or a choice of format
  first. If a format is asked for, PDF is picked and nothing else.
- Whether a statement PDF is served from card.apple.com itself. That is
  the only host this app will read from. If the recording shows another
  Apple host, that one host is added and nothing wider.

## Files

- `Statements\` holds both kinds of statement, told apart by name,
  `2026-08-31 Apple Card Statement.pdf` and
  `2026-08-31 Apple Card Savings Statement.pdf`.
- `Tax Documents\` holds `2025-12-31 Apple Card 1099-INT Tax Form.pdf`,
  filed at the end of the tax year like every other app here.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9270, sign in yourself
paperpull applecard record        REM the recording, the useful one
paperpull applecard diagnose      REM the survey, for the maintainer
paperpull applecard pilot         REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** An Apple Account sign-in is happiest in the
  browser already on the machine, so `login.bat` launches it with a
  separate profile on port **9270** and leaves the sign-in to you.
- **Three sections.** Discovery opens the card's statements, then the
  Savings statements, then the tax forms, and reads every control whose
  name says it fetches one document. An account without Savings simply
  has no second section.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  pressed once, after the guard has passed it, and whatever the site does,
  a download, a PDF response or a new tab, is caught and saved.
- **Nothing is downloaded twice.** A document already in `progress.json`
  is skipped forever, even if you delete the PDF afterwards.

## Safety

- Read-only. `FORBIDDEN_CONTROL_RE` refuses anything that pays, schedules,
  transfers, adds money, withdraws, moves money between the card and
  Savings, touches Daily Cash or Apple Cash, disputes, reports a card
  lost, shows a card number, asks for a new card or a higher limit,
  shares the card, links a bank account, opens or closes anything, or
  edits a setting. A control must also look like a document action, or
  be exactly Statements, Savings or Documents, before it can be pressed.
- Only `https` addresses on `card.apple.com` are ever read. Not
  `apple.com` as a whole, which would take in the Apple Store.
- Diagnostics mask every run of six or more digits, every amount, every
  email address and the account holder's name.

## Tests

```bat
.venv\Scripts\python.exe -m pytest tests -q
```
