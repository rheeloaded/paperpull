# Newrez document downloader

**Working on the tester's account.** This app was built without a
Newrez mortgage and repaired over several rounds from the surveys,
failure files and a recording one tester sent. Discover reads each year
the statements page's year picker offers, and on his account it walked
three years and every document downloaded, named for the dates printed
on them. The conversation is
[issue #38](https://github.com/rheeloaded/paperpull/issues/38).

Downloads your Newrez **mortgage statements and 1098 forms** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Newrez**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   Newrez folder. It downloads nothing, clicks nothing but a documents
   link, takes no screenshot, and masks any run of six or more digits. On
   the statements page it also chooses each year in the year picker, to
   read that year's list, and does nothing else there.
5. Click **Record**, in the same **more** menu. Go back to the browser window
   and click your way to one document the way you normally would, then come
   back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough, written
   for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach both files to [issue #38](https://github.com/rheeloaded/paperpull/issues/38)
   with a sentence about how you get from the dashboard to your statements, and whether the 1098 sits with them or on a tax page.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Tax Documents\`, then attach a fresh Diagnose file.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps. The same
   goes for the lines that begin with `Year picker` or `No year picker`,
   which say which years were read and how many statements each gave.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to the issue the same
way. It is what keeps the rounds after the first one short, and it is
described in full on the
[Testing a provider](../../docs/testing-a-provider.md#if-a-run-fails-send-the-file-it-wrote)
page.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9257, sign in yourself
paperpull newrez diagnose         REM the survey, for the maintainer
paperpull newrez pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Newrez's portal is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents.** From the dashboard, **Account Details** leads into the
  servicing app at servicing.newrez.com, where the monthly statements and
  the yearly 1098s each have their own page (from two surveys, #38). Every
  control whose name says it fetches a statement, an escrow analysis or a
  1098 is read, and the date comes from the control's name or the row it
  sits in.
- **Years.** Recorded, from a tester's **Record** file (#38). The monthly
  page shows one year's statements at a time, with a year picker above
  the list, and choosing a year draws that year's list a moment later.
  Discovery reads the list the page shows first, then chooses each year
  the picker offers and reads that year's list only once every statement
  on screen is in that year, so a list left over from the year before is
  never read as the new one. A download that does not find its row on the
  list as drawn chooses the statement's own year first, and presses
  nothing if that year's list never shows. The picker is a dropdown with
  no name of its own, so it is known by offering nothing but years after
  one placeholder at most. Choosing one of the years is all the app does
  to it, and a dropdown that offers anything else, sits in a form with
  more to fill in, or has words near it that name an action is left
  alone. What the picker's first option says was not recorded. His three
  years with statements account for the other three options, so the
  first is taken to be a placeholder such as Select Year, and it is never
  chosen. A dropdown with two options that are not years, or one anywhere
  but first, is not used, and the `No year picker` line says so. The
  yearly page is walked the same way only if it turns out to have a
  picker too.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Tax Documents\`. A document still visibly on its way
  when the usual wait ends, a file still being written or a request that
  could be it still waiting, is waited for up to 45 seconds more.
- **The control that is pressed.** The control is held as the element the
  guard approved, and its name and date are read again right before it is
  pressed, so a list that redraws cannot move the press to another row. If
  the control has changed, nothing is pressed and the document is left for
  the next run.
- **A late download.** Every statement downloads under the same name, so
  the download folder is watched for what an earlier statement left
  behind. Before a row is looked for, a download still being written is
  given up to 30 seconds to finish, and one that has not grown for 5
  seconds is taken as abandoned. If one is still growing after 30 seconds,
  nothing is clicked and the document is left for the next run. A PDF that
  lands after such a download has gone, or next to a second new PDF, is not
  taken, since the folder cannot say which one it is. It stays in the
  folder and the document is asked for again on the next run. This cannot
  see a download whose server has not answered yet, which has no file, so
  such a download landing during the next statement's capture is not
  caught here. For a statement the date check below is the backstop, and
  for a 1098 there is none.
- **Dates.** The statements list gives a month and a year and no day, so a
  statement is saved under the last day of its month and then named for the
  date printed beside "Statement Date" inside it, when that date falls in
  the same month. A tester confirmed that his statements print
  `Statement Date: mm/dd/yyyy` and that files were renamed and saved under
  the right date (#38). The app remembers each statement by its month, so
  nothing already downloaded is fetched again, and **Rename preview** then
  **Apply renames** bring files saved by an earlier build into line.
- **The right statement.** A statement whose first date after "Statement
  Date" falls in the month of another statement on the list, with no date
  of its own month near that label, is not saved under this one's name
  unless that date is the one a "Due Date" label names on its own line. It
  goes to `Manual Review\` and the statement is asked for again on the next
  run. One whose dates are in some other month, or disagree, keeps its
  month's name with a note, and **Rename preview** lists any file already
  saved that looks that way, so it can be opened and checked. The label it
  reads is the one a tester's statements print (#38), and a statement
  refused this way has not been seen on a real run yet.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, schedules a payment, sets up autopay, requests a payoff, an escrow change or hardship help, uploads anything, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the documents area lists. Monthly mortgage statements, the yearly 1098, and escrow analysis statements if they sit on the same page.
- One loan per sign-in is assumed. If you have more than one Newrez loan, say so in the issue, the survey will show how the site switches between them.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull newrez add-account NAME`).
