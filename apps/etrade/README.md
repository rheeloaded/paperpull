# E*TRADE document downloader

**Working on the tester's account.** This app was built without an
E*TRADE brokerage or retirement account and repaired over several rounds
from the surveys, failure files and download attempts one tester sent.
Since 0.39.0 it reads each statement's PDF out of the site's own answer,
and a Pilot and then a full run on his account saved every statement. No
tax form has been seen yet, since his account has none. The conversation is
[issue #36](https://github.com/rheeloaded/paperpull/issues/36).

Downloads your E*TRADE **statements, trade confirmations and tax forms** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page. The first time you open
   PaperPull it shows its terms and asks which folder your documents go in,
   then shows the same list by itself. Click **ETRADE**, then **Continue**,
   then **Set up**. Back on Accounts, click **ETRADE** to open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Unlike the one on the provider's page, it starts no download once
   you are signed in. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Back in Get help, click **Make the report**. This support report reads
   the documents page and writes `Diagnostics\diagnose-documents.json` in
   the E*TRADE folder. It downloads nothing, takes no screenshot, and writes
   any word that is not on PaperPull's fixed list as its shape. It presses
   only links and buttons that lead to the documents or show more of them, a
   documents link or "Show more" for instance.
5. Once the report is done, click **Back to ETRADE**, then **More**, then
   **Get help** again, and click **Record steps**. Go back to the browser
   window and click your way to one document the way you normally would,
   then come back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough,
   written for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach both files to [issue #36](https://github.com/rheeloaded/paperpull/issues/36)
   with a sentence about how statements, confirmations and tax forms are separated (tabs, a dropdown, one list), and how you choose the account.
8. When a new build is posted, click **Try the newest few first** on the
   provider's page and say whether PDFs landed in `Statements\` or
   `Tax Documents\`, then attach a fresh support report. If it says to sign
   in first, sign in from Get help as in step 3 and click it again.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps.

A support report and one recording together are usually enough to get a
provider working in a single round. A support report on its own takes two
or three.

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
login.bat                         REM opens Edge or Chrome on port 9260, sign in yourself
paperpull etrade diagnose         REM the survey, for the maintainer
paperpull etrade pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Etrade.com runs bot protection that is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents.** Discovery tries the documents and statements routes on us.etrade.com in turn and takes the first that is not a sign-in page and looks like a documents list. Every control whose name says it fetches a statement, a confirmation or a tax form ("View", "Download", "Statement PDF", "1099") is read, and the date comes from the control's name or the row it sits in.
- **Every page of the list.** The page asks E*TRADE for one page of a
  period's list at a time, and the answer says how many documents the
  whole list holds. Discovery asks for each later page the same way, from
  inside the page and only at the list's own address, until it has them
  all. When a page cannot be read, the run keeps the list it found, writes
  a failure file saying why in fixed words, and stops before it downloads
  anything or moves a saved statement to another record, since both rest
  on the whole list. A statement the list gives no account is told apart by
  its place among those of its date and title, never by E*TRADE's ids for
  it, which change every time the list loads, and a record told apart that
  way is taken only while the lists still show its date and title shared
  with no account (#96). The download finds a statement's row on the page
  it shows, so for one listed on a later page it presses the list's own
  Next page button, the button labeled exactly "Next page" in the list's
  pagination, only while that button is on and only until the page shows
  a row of the statement's date naming its title.
- **Accounts.** Each statement in E*TRADE's list carries a key for its
  account, and the page loads its account list beside the documents,
  which gives each key the label the Account column shows, "words -
  1234". Discovery reads that list from the page's own answer, as it reads
  the documents, and gives each statement its account's label (#119). A
  closed account's label, ending in "(Closed)", is still that account. A key the
  list gives no label, or two labels, gives the statement no account,
  never a guessed one. When the account list was not read at all, or the
  lists give no account to a statement a saved record holds under its
  account, Discover writes a
  failure file and stops before it records, moves or downloads anything,
  since every statement would read as one of no account and be taken
  again. One account's two documents of one title and day, two trade
  confirmations, are kept as two and marked for manual review, since no
  link on the page tells them apart. The record is kept under the label's last digits,
  which renaming the account on E*TRADE does not change. The key itself is
  never kept, and neither it nor a label is written to a log, a trace or
  a failure file.
- **Downloads.** The documents page lists one period at a time, so the
  period that lists the document, its year or Year To Date, is chosen
  first. Two documents can share a date, so the row taken is the one
  whose link names the document, its whole words or label the title,
  the title then PDF, or the title then PDF for the account. An element
  whose own text is the title while a child adds more words, a link
  reading the title with "Privacy Notice" in a span inside it, does not
  name it. A row is taken by its date alone only when it is the only one
  and the lists the page loaded held one document on that date, with
  this document's title whenever the lists named it. Of what a row offers, its box aside,
  nothing is pressed for a document when something else that could be
  pressed sits inside it, so a cell holding this document's link beside
  another document's or an insert, a clickable container holding an
  insert's View, or a card wrapping a notice's link is never pressed
  whole. Anything inside a link or a button is judged as that link or
  button, since a press on it presses them too, so the title in a span
  inside an insert's link is the insert. A link whose words mark it as
  an insert is never taken. Inside the chosen row a View, a pointer or
  the row's box is used only when the row holds this document and no
  other. A row that names another document of the date, prints another
  date, holds two boxes, repeats a control, or is one of fewer rows of
  the date than the lists held documents gets only this document's own
  name pressed. Only a row that looks like a document's own counts
  toward that, one that prints the date and no other, prints a title the
  lists gave that date, and holds a bare View or Download or a control
  carrying such a title. A filter chip that prints the date does not
  count, and neither does a notice with a View of its own. A control
  that does not name the document is pressed for it only when it is a
  bare View, Download, Open, Print or PDF, alone or followed by words
  like statement, or when its row nowhere prints the document's title,
  holds no bare action, and holds no other control that says something
  else. Every control in the row counts for that, links, buttons, input
  buttons, pointers and elements the page made clickable, not links
  alone. An insert does not count as one, since it is never pressed.
  Every step follows that rule, the steps that take a row's link and the
  only control of a date included. A control found before the row walk
  has to sit in one row, the nearest element around it that prints a
  date holding a single element that prints one. Each element is held
  from the check to the press, so a list that changes in between cannot
  move the press. Every word an element carries, what it shows and its
  label, goes through the guard, except the account a link names after
  "PDF for". The page's Download button is pressed only through the
  row's box, never as a document's own control, and only when the page
  has one outside every document row, this row's own box reads ticked,
  and it is the only box ticked, and a box the app ticked is cleared
  again. A PDF the site sends back as an answer is taken only when the
  request for it, or the request a redirect came from, was made during
  this document's attempt, so a late answer to the one before is not
  saved under this name. Pressing a document's link makes the page ask
  E*TRADE for it, and the answer is JSON with the PDF inside it as
  base64, which the page hands to the browser as a download. The app
  reads the PDF straight out of that answer, which is tied to the press
  the same way. A download event, or a file that lands in the download
  folder, is not yet tied to the click that way, so an answer that is
  wins over them. An answer that holds no PDF is written to
  `download-attempt.json` by its shape alone, how many texts it held,
  the length of the longest, and whether that one is base64 and encodes
  the start of a PDF, a zip or a gzip.
  When the app cannot tell which row or control is the document's it
  presses nothing and says so in `Diagnostics\download-attempt.json`, in
  counts and fixed words.
  A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Tax Documents\`.
- **Resume reads the lists first.** The choice of row rests on what the
  lists said, how many documents each date held and their titles, so
  Resume runs discovery before it downloads, as Pilot and a full run do.
  Without them a row that does not name its document would be refused.
- **What the download writes down.** `download-attempt.json` and
  `discovery-trace.json` are meant to be attached to a public issue, so
  they are built from what may leave. Fixed words, counts and yes or no
  answers, the document's date, the period words and the dates each
  period listed, the kind of each candidate control, exception names,
  HTTP methods, status codes and content kinds, and for the row's
  outline the tags, classes and roles with the shape of each piece of
  text. A period is a word from a fixed list, Year To Date, Last N Days
  or Months, All, or a year 19xx or 20xx, so digits printed on the page
  are never read as one. Each address is written as whether it is
  E*TRADE's, the words of its path that are on the list of words
  E*TRADE's pages were seen to use, a file's ending, and the names of
  its parameters that are on the list of names E*TRADE was seen to use,
  never their values. A request's body is written as the names of its
  keys from that same list. Every other word or name is written as #.
  Never the page's own words, the account column included.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that trades, buys, sells, places or cancels an order, transfers, wires, deposits, withdraws, takes a distribution, links a bank, or edits the account. A control that signs in, signs out, logs out or logs off, or that changes a setting, is refused too. Every control pressed for a document, the row's box aside, must also look like a document action, on every step, the row walk included.

## Scope

- Whatever the documents area lists. Statements, trade confirmations and tax forms, filed to `Statements\` (confirmations included, named Trade Confirmation) and `Tax Documents\`.
- Trade confirmations arrive per trade and can run to hundreds. If you only want statements, drop nothing yet, the first survey shows how they are separated and the second round adds a switch.
- The documents list shows every account on the sign-in together, each document's account in a column of its own. Each statement keeps that account, which a naming pattern can use as `{account}`. When the sign-in has more than one account, a file's name and the index's Document Summary end with the account, and a sign-in with one account keeps the names it always had. A download takes only the link naming its own account, so two accounts' statements of one title and day are each saved as their own (#96). With one account, statements saved before keep their records and names. With more than one, the list cannot tell which account a statement saved before belongs to, so Discover reads its saved PDF, and the record takes an account only when the file prints that account's last digits as an account number (XXXX-1234, 6789-1234, ...1234, "Account Number" or "Account ending in" before them), no other listed account's digits appear anywhere in it, and it prints no other account number, a closed account's included. A record of that account already under its own key, done or holding a file such as a review copy, keeps its place. Such a statement is not downloaded again, and its record takes the account and the name a statement downloaded now would have, so its file keeps its name and folder until a Rename gives it that name, the account in it. Any other statement saved before stays as it is, and its account's copy is downloaded once more, named with the account. A year, an amount, a phone number or a tax id is never read as an account, and only counts go in the log.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull etrade add-account NAME`).
