# PG&E (Pacific Gas and Electric) bill downloader

Downloads your monthly **billing statements** as PDFs from the PG&E
account portal (`myaccount.pge.com`). Read-only, delete-safe, and part of
[PaperPull](../../README.md).

## Setup

```bat
setup.bat                         REM one-time: create the venv + install Playwright
login.bat                         REM opens a browser on port 9244, sign in yourself
paperpull pge pilot               REM download the newest 5 bills as a test
paperpull pge all                 REM download every available bill
```

The first run asks *"Whose account is this?"* and the name you enter is saved
to `config.json` and stamped on every bill (the **Account Holder** column of
the index CSV).

## How it works

- **You sign in.** `login.bat` opens a browser window using this app's own
  profile and port (9244). You complete sign-in and 2FA yourself, then open
  **Billing and payments** so the bill history is on screen. The tool attaches
  to that signed-in browser over CDP and reuses that tab.
- **Discovery** reads every page of the bill history (the portal's "Jump to"
  page picker is the only control it operates outside a bill row) and lists
  one statement per bill date.
- **Download** finds the bill's row again (a row that reads View Bill PDF
  and carries that bill's date, so a payment made on the same day is not
  taken for it) and clicks its **View Bill PDF** control, or, when the row
  has none that passes the guard below, the first other control in it that
  does. When no such row is found where the rows are usually read, every
  control on the page that could be a bill's PDF is followed to the row it
  sits in, and a row is used only when it passes the same test (it reads
  View Bill PDF and carries the bill's date) and no other row reached that
  way does. A row that reads View Bill PDF more than once holds more than
  one bill, and it is not used either. When the bill's own row was found,
  no other row is ever used, even when the bill's row hands over nothing. The PDF arrives as a
  download, a network response, a blob in a popup, a PDF in a popup, or a
  viewer in the page, and all of them are handled. A blob is read by the
  page that made it, and when the page's security policy refuses that
  read, it is saved as a download from that page, the way the original
  contributor captured it. The popup itself is asked only after that. A
  PDF in a popup is asked for through the signed-in session first, and
  saved with a download link only when it is on the history's own origin,
  so the history tab never moves. Every tab that opened during the press
  is closed afterwards, whether or not the bill was saved.
- **The right bill.** Only what the press brought is saved. An answer counts
  only from PG&E's own hosts and from the history tab or a tab it opened
  during that press, so a PDF another tab loads at the same moment is not
  the bill, even in a tab the history opened earlier. Nothing the page held
  when a bill's press began is read for that bill, not a viewer's address
  and not the address any of its frames had moved on to.
  A download of an address an earlier bill already had (a blob, or a PDF
  this tool saved with its own download link) is never saved under a later
  bill's name. When nothing new arrives, the bill fails and says so. One
  limit remains. Something an earlier press brings very late, after the
  next bill's press has begun, cannot be told apart by timing alone.
- **Read-only.** Every control in a bill row is judged by every label it
  carries (its text, aria-label, title and label attribute, and the text an
  aria-labelledby points at) before it is clicked. It must read as a
  document action (view, download, PDF, bill) and no label may match
  anything that pays, enrolls, changes service or edits the account. A
  row's **Pay** control never qualifies.

  A click on an element is also a click on everything it sits in and on
  whatever sits under the mouse inside it, so a control is pressed only
  when everything a click on it could reach passes too. That is every
  control around it up to the page and every control inside it, the
  control of any label among them, and every labeled box around it within
  its row or inside it, whose label may carry no forbidden word. Shadow
  roots are followed the way a click travels, through the slot a word sits
  in. So View Bill PDF text inside a Pay button, a link inside a box whose
  label says Pay, and a label that hands its click to a Pay button are
  never pressed. The page wide look, which runs only when the bill's row
  was not found, judges the row it reaches in exactly the same way.

  A closed shadow root cannot be seen into from the page at all. A control
  that is, sits in, or holds a component the page defined whose inside
  cannot be read, within its row, is refused rather than guessed about,
  since that is how a closed shadow root on such a component looks from
  outside. A closed shadow root on an ordinary element, or on a tag the
  page never defined, looks like no shadow root at all to this check, and
  is not caught. Salesforce's own lightning components are not counted, and
  neither is anything above the row, since the whole page sits in
  components. The row outline the log prints follows open shadow roots
  only. The outline of the tester's bill rows showed no control, label
  element or component around the link.

  The press is never forced, so it lands on the approved control and never
  on whatever might sit on top of it, and a press is never repeated once it
  has arrived. There is no code here that submits a form or confirms a
  dialog.
- **Delete-safe.** Once a bill is downloaded it is marked done for good, so
  deleting the PDF after importing it elsewhere does not bring it back.

## Validation status

Ported onto the shared core and the standard command set. The bill history
parsing, pagination and PDF capture were worked out against the live portal
by the contributor. The rebuilt orchestration (run summary, index CSV, PDF
validation, resume) is covered by automated tests but has not had a fresh
live pilot. Start with `paperpull pge pilot` and inspect its results.

## Maintenance

Page behavior is in `pge_site.py`, the command flow in `pge_docs.py`. When
the portal changes, `paperpull pge diagnose` writes what it sees (row counts, sample
rows, every control and whether the guard would allow it) to the Diagnostics
folder along with a screenshot.
