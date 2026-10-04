# State Farm document downloader

**Working on the tester's account.** This app was built without a State
Farm auto, home or life policy and repaired over several rounds from the
surveys, failure files and a recording one tester sent. Discovery reads
State Farm's own list of documents, and on his account a full run saved
every document that list holds for his policies. What the page showed is
marked RECORDED in `statefarm_site.py`, and what is still a guess is marked
GUESS. The conversation is
[issue #37](https://github.com/rheeloaded/paperpull/issues/37).

Downloads your State Farm **bills, renewal notices, ID cards and payment receipts** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **State Farm**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   State Farm folder. It downloads nothing, clicks nothing but a documents
   link, takes no screenshot, and masks any run of six or more digits.
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
7. Attach both files to [issue #37](https://github.com/rheeloaded/paperpull/issues/37)
   with a sentence about how bills, ID cards and policy documents are separated (tabs, per policy, one list), and what the download control is called.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Insurance Documents\`, then attach a fresh Diagnose file.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps. Copy the
   lines Discover prints under its counts too, which say how State Farm's
   list answered for each year. They hold counts, years and fixed words
   only.

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

## What is known, and what is a guess

Known from the tester's surveys, recording and Pilots (#37), marked
RECORDED in the code.

- **Sign-in lands on My Accounts** at my.statefarm.com. The documents are
  in the Document Center on edocuments.statefarm.com, behind "View
  documents & PDFs" and "Documents (excludes claims)".
- **The Document Center fills itself from one list call**, whose answer
  names each document with the day it was made, its type, its category, a
  document id and a field for a file address. A document is dated by the
  day it was made. The "Available online until" date under its title is two
  years later and is never used.
- **The list call carries a year in its query**, and the value the page
  itself sends there is not a four digit year. Discovery used to change
  four digits only, so it never asked for an earlier year. It now sets the
  year to each one in turn, whatever the page put there, and Discover says
  which kind of value the page sent.
- **Each row keeps its documents folded behind its own button**, named
  View Documents with the row's number after it. A document the row
  reveals is named after what it is, "Renewal Notice" and then the vehicle
  for one, and pressing it opens the document in a new tab.
- **Pressing View Documents draws the row anew.** The button pressed leaves
  the page, and a button with the same name is drawn in its place with the
  documents inside the new row. The app finds that row again by its date
  and presses a document only when it sits inside the one row on the page
  that carries the date. Two rows with the date, or none, press nothing.
- **The documents appear in the page itself.** The revealed document was
  among the page's own controls, so it is not in a frame. The four dialogs
  and two frames every failure file counted were on the page before
  anything was pressed, and pressing View Documents added one link and a
  few elements to the page and no dialog, so nothing says it opened one.
  A document found outside its row, in a dialog or anywhere else, is not
  pressed, and the trace says where it sat.
- **The list gave no file address for the document tried in 0.37.1**, only
  an id, so its row is the way to it. Discover now counts how many
  documents came with a file address, with one that is not a path, or with
  none.

A guess, marked GUESS in the code.

- **The Time Period menu asks for a year by its four digits.** The menu
  offers years back to 2023. Discovery sets the list's year to four digits
  for each earlier year, and Discover prints the status and count each year
  answered, so a wrong guess shows there first.
- **An older document's row appears once the page's own list call asks for
  its year.** A download of one reloads the Document Center with the year
  in that one call set to the document's, changing nothing else in it and
  pressing nothing to get there.
- **State Farm keeps about two years.** The walk stops after two years
  running with nothing in them.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9261, sign in yourself
paperpull statefarm diagnose         REM the survey, for the maintainer
paperpull statefarm pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Statefarm.com's sign-in is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents.** Discovery opens the Document Center on
  edocuments.statefarm.com and reads the list the page loads for itself,
  then asks the same list for each earlier year until two years running
  have nothing in them. Each document is dated by the day it was made.
- **Downloads.** A document the list gave a file address for is fetched
  from inside the page with the session's own cookies. Otherwise its row
  is found by its date, the row's View Documents is pressed once, and the
  document the row reveals is pressed only once it has passed the guard
  and sits inside the one row on the page that carries that date. Its
  type, before the dash, faces the whole guard and has to be the type the
  list gives. Its description faces the whole guard as well, less a
  description that is only Billing/Payments or how a payment was made,
  and the trim Limited in a vehicle's name, so those no longer keep a
  document away. A description that is word for word what State Farm's
  own list calls the document, its description or its category, is read
  again with the money words a receipt is described by let off, payment,
  paid, billing, receipt and a card ending in its last four, and every
  other word of the guard still facing it (#37). When the guard
  still refuses one, `download-attempt.json` gives its words from a fixed
  list of ordinary ones, any other word as `*` and digits as `#`. The PDF
  it opens is caught and saved to `Statements\` or `Insurance Documents\`.
  A document from an earlier year is looked for in the list of its own
  year.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, sets up autopay, files or reports a claim, changes coverage, adds or removes a vehicle, driver or policy, starts a quote, cancels or renews anything, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Bills and renewal notices file to `Statements\`, ID cards and policy documents to `Insurance Documents\`, payment receipts to `Statements\` as Receipt.
- State Farm keeps documents per policy. The first survey shows how policies are switched, and the second round drives it, so a first Pilot may only see one policy.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull statefarm add-account NAME`).
