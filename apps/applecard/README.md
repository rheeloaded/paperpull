# Apple Card and Savings document downloader

**Working on the tester's account.** This app was built without an
Apple Card or a Savings account and rebuilt from the recording and
Diagnose files one tester sent, marked RECORDED in `applecard_site.py`,
with what is still a guess marked GUESS. Since 0.39.0 it takes each
statement's PDF where the page builds it, and a Pilot and then a full run
on his account saved the card's statements, the Savings statements and
the 1099-INT forms. The conversation is
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
5. Click **Diagnose** as well, in the same **more** menu. It downloads
   nothing, presses nothing but a Statements, Savings, Documents or Tax
   Documents link, and takes no screenshot. It writes two files. The one
   whose name starts with `survey-diagnose-` holds counts and states and
   no text from your account, and that is the one to send.
   `diagnose-documents.json` beside it is the detailed one. It carries
   the page's own words, the headings and the names of buttons and
   links, the months of your statements among them, so it stays on your
   machine.
6. Open each file you will send in Notepad and read it through. The
   recording holds the names of the buttons and links you pressed and
   the shape of the data the page loads, no values. It ends by printing
   anything worth a second look. If anything in either file looks
   personal, delete that line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach `recording.json` and the `survey-diagnose-` file to
   [issue #52](https://github.com/rheeloaded/paperpull/issues/52) with a
   sentence about where you found each kind, and how far back the lists
   go. Do not attach `diagnose-documents.json`, which carries the page's
   own words. Do not attach a screenshot of a statement either. A
   statement carries your card and account numbers, and the recording
   deliberately does not.
8. When a new build is posted, click **Pilot** and say whether PDFs
   landed in `Statements\`, and whether the card and Savings statements
   came out with the right names and months. A Pilot saves the five
   newest documents, which are usually all statements, since a tax form
   is filed at the end of its tax year. Tax forms come with a full run.

One recording is usually enough to write the first working build. Expect
a few Pilot runs after it, each with a word about what came out wrong,
which is the normal shape of it and not a sign anything went wrong.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. When the app reaches a list and
will not read it, because the list failed one of the checks below, the file
names that list and each check as true or false. A document that would not
save also leaves `download-attempt.json`, which says what the site answered in
fixed words, counts and flags, with an address cut down to whether it is
card.apple.com's and the plain words of its path. Attach both to the issue the
same way. They are what keep the rounds after the first one short, and the
failure file is described in full on the
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

Known from the first recording and Diagnose from a real account (#52),
marked RECORDED in the code.

- **The lists are reached through the menu, never by address.**
  card.apple.com draws each section itself. Typed in, only the front page
  and `/savings` answer, and every section address the first build
  guessed came back 404. So the app loads the front page only, waits for
  its menu, which took several seconds after a fresh load, and presses
  links the way the tester did.
- **The card's statements** are the menu's Statements.
- **Savings statements and tax forms** are under the menu's Savings, then
  Documents, then Statements or Tax Documents, each shown with its count.
  The menu's own Statements link is still on that page and is the card's,
  so those two presses look only in the page's content, and only at a
  link that carries a count, which the menu's never does. A link whose
  count is 0 opens a list with nothing to save, which is not a failure.
- **Every document is one button** named "Download statement of
  <month> <year> (PDF)", on all three lists, a 1099-INT's included, and
  pressing it downloads the PDF, with no new tab and no choice of format.
  Only a button named exactly that way is read as a document, and it is
  dated by its own name. The first Diagnose found another control on the
  Savings page, one that holds no document, whose name the app's wider
  pattern took for a document's. So anything else on a list, a link to
  terms or a policy for one, is counted and never read or pressed. Two
  buttons that name the same month on one list are both left alone,
  since pressing one would be a guess.
- **The lists are checked before they are read.** Since the buttons on all
  three lists look alike, a list is not read until none of the buttons
  that were on screen before the press is still there. The card's list
  must also have no link back to Savings' Documents, which the Savings
  statements list carries, and a list opened from a link with a count
  must not hold more documents than that count. A list that fails any of
  these is not read, and the app opens it again from a freshly loaded
  front page. If it fails again, nothing is saved from it and the
  failure file says which check refused it.
- **Apple names each file for its document**, "Apple Card Statement -
  <month> <year>.pdf", "Savings Statement - <month> <year>.pdf" and
  "1099-INT <year> - Tax Form.pdf". When the download arrives with one of
  those names and it names another document than the one the app asked
  for, another kind, another month or another tax year, the file is not
  saved.
- **The tax year of a tax form** is the year its button names. The
  recording's 1099-INT button saved a file Apple named with the same
  year, and the tax year printed on that form matched it. So each form is
  filed at the end of the year its button names, and a form whose file
  Apple names with another year is not saved.

Known from the first Pilot on a real account (#52, 0.37.1).

- **A download reaches the app.** Three statements were saved, card and
  Savings both.
- **A press can download without the app seeing it.** On the card's
  statements and on the Savings statements alike, the first press on a
  list the app had just opened seemed to produce nothing, and 0.38.0 pressed
  once more. The tester then saw Chrome download that statement twice, its
  own download menu open in the address bar, while nothing reached the
  folder the app watches or its download event. So the app now also takes
  the PDF where the page builds it, before the browser does anything with
  the download, and checks Apple's name for it like any other arrival. A
  press that produces nothing at all is still made once more, and one that
  puts anything new on the page is never repeated.

A guess, marked GUESS in the code.

- **Whether a tax form's row says 1099-INT.** If it does, the file is
  named 1099-INT Tax Form, and if not, Tax Document.
- **Whether the menu's Statements, pressed on a Savings page, keeps the
  Savings address.** If it does, the app loads the front page and presses
  Statements from there, and a card statement is never read as Savings
  either way.
- **Whether the tax list shows the same link back to Documents** as the
  Savings statements list. Nothing depends on it. The card's list is told
  from both by having none.
- **Which host serves the PDF.** The recording saw each download arrive
  with its file name and saw no request for it on card.apple.com. The
  app catches the download itself, so this does not stop a save, and
  card.apple.com stays the only host it reads from. If a PDF turns out to
  come from another Apple host, that one host is added and nothing wider.

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
  Savings statements, then the tax forms, each through the menu, and
  reads every button whose name says it fetches one document. An account
  without Savings simply has no second section.
- **Downloads.** The row's own button is pressed once, after the guard
  has passed it, and the PDF it downloads is caught and saved. A PDF
  response or a new tab would be caught too. A run takes one list at a
  time, the card's statements, then Savings, then the tax forms, newest
  first within each, so it walks the menu once per list and not once per
  document.
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
  An overlay is cleared only with Escape or a button whose whole name is
  Close, Dismiss, No thanks or Not now, so "Close Apple Card Account"
  is never pressed.
- Only `https` addresses on `card.apple.com` are ever read. Not
  `apple.com` as a whole, which would take in the Apple Store.
- The files you are asked to send, the `survey-diagnose-` file,
  `failure-*.json` and `download-attempt.json`, are built from a list of
  what may leave, counts, states, flags and fixed words. The detailed
  `diagnose-documents.json` masks every run of six or more digits, every
  amount, every email address and the account holder's name, and stays
  on your machine.

## Tests

```bat
.venv\Scripts\python.exe -m pytest tests -q
```
