# Simmons Bank loan documents

Downloads the statements, notices and tax forms of a Simmons Bank loan from
the bank's online banking (Banno, by Jack Henry) at
`login.simmonsbank.com/documents`, as PDFs. This reads from a browser where
you sign in yourself, on the port named in `config.json` (see
`config.example.json`, port 9298). Passwords and verification codes are
never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

**A paid-off loan's documents go away.** Simmons Bank keeps the documents of
a loan that is paid off only until a date it names, and after that date
they are gone from online banking. On the account this was built on that
date is 2032-06-30. Discover prints the date your own account names
("documents available until YYYY-MM-DD"), so run Run All before then.

## Validation status

**Run live on one account on 2026-10-15.** The account owner surveyed a
signed-in account read-only, then ran the app on it the same day. The
account holds one thing at the bank, a paid-off ARM mortgage, with 27
documents on the Documents page (22 monthly loan statements, 3 notices and
2 tax forms, January 2030 to October 2031). Discover listed the 27 and
printed the date the bank keeps them until, Pilot took the newest
statement, Run All took the rest, and Verify found 27 index rows with no
problem. Every PDF came as the browser's own download. What the survey and
the run showed is below.

- Every control on the page is drawn inside open shadow roots of Banno's
  web components. The page's own text reading sees none of it, while the
  browser automation reads into open shadow roots, which is how the app
  reads the page, and the core's press reached each row's button there.
- Loading the Documents page makes the page ask the bank for its list of
  documents, one entry per document with its id, its type (statement,
  notice or tax), its title, its date, its file name and its account. The
  app hears that answer. It asks the list nothing itself, unless the
  browser no longer holds the answer's body, and then it asks that exact
  address once more.
- The page draws one row per document, a button reading the document's
  title, its type and the account ("Loan Periodic Statement October 2031
  Statement, RE ARM ... (x....)").
- Pressing a row makes the page ask the bank for that document's PDF and
  hand it to the browser as a download named for the document's own file
  name. No tab opens and the page stays where it is.
- The first run sent 14 of the 27 to Manual Review, since the PDFs print
  their dates as numbers a few days off the list's date: a statement's
  "Statement Date 04/13/30" for a document the list dates the 11th, a
  notice's "Effective Date 8/05/30", and the tax form, titled "1098 Tax
  Reporting January 2031", prints "For calendar year 2030". The text check
  now reads those (see "What it does"), and the second run filed all 27.

Not seen yet are a Simmons account with deposit accounts or more than one
loan (the list stops when its documents name two accounts), the bank's
sign-in page as the app meets it mid-run, and how long an idle session
lasts.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page. The first time you open
   PaperPull it shows its terms and asks which folder your documents go in,
   then shows the same list by itself. Click **Simmons Bank**, then
   **Continue**, then **Set up**. Back on Accounts, click **Simmons Bank**
   to open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Unlike the one on the provider's page, it starts no download once
   you are signed in. Your own Edge or Chrome opens with a separate profile.
   Sign in to Simmons Bank online banking yourself and leave the window open.
4. Back in Get help, click **Make the report**. This support report opens
   the Documents page by its address and writes
   `Diagnostics\diagnose-documents.json` in the Simmons Bank folder. It
   downloads nothing, clicks nothing, takes no screenshot, and writes any
   word that is not on PaperPull's fixed list as its shape.
5. Once the report is done, click **Back to Simmons Bank**, then **Try the
   newest few first**. It saves the newest document and stops. Open the PDF
   and check it is the document of the date in its name.
6. Open the Diagnostics file in Notepad and look through it. It should hold
   counts, no values. If anything in it looks personal, delete that line.
7. Attach it to a new
   [provider issue](https://github.com/rheeloaded/paperpull/issues/new/choose)
   titled "Simmons Bank", with a sentence saying whether step 5 saved the
   right document.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it, with
no text from your account in it. Attach it to the issue the same way.

## Setup and use, for a checkout

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull simmons diagnose`, then `paperpull simmons pilot` (one document).
5. Check the downloaded document before using `paperpull simmons all`.

## How it works

The app opens the Documents page by its address and reads the list whole
before anything else. The list is the answer the page itself got from the
bank, which has to be one answer holding nothing but its documents, every
document of a known type, with an id, a title, a real date, a PDF file name
and exactly one account, no id twice, and one account across the whole
list. The day the list was asked from has to be the bank's own first day of
documents, and every document dated on or after it. The rows the page draws
have to name exactly the answer's titles and types, as many of each, all of
the one account, each the only row of its list item, read twice alike. If
the bank's accounts answer shows more than that one account, the list
stops. Anything else stops the list rather than being called whole.

Before each document the page is loaded again and the list read again, and
exactly one document there must carry the record's id and date, and
exactly one row its whole text. Only that row's button is pressed. The PDF
is kept only when the press made the page ask that one document's own PDF
address, once, and brought exactly one browser download, a Blob of the
bank's own page named with the document's own file name. When no download
comes, that exact address is asked once more with the browser's own
cookies and no redirect followed, and the trace says which way the PDF
came. A tab, a second download, a request for another document, a download
named for another file, or a file landing with no download event, and
nothing is kept. Then the PDF's own text has to name the document, by the
document's date, or the month its title names, or a date printed as a
number of its own within three days before to ten days after the list's
date and inside the title's month (a statement prints its own "Statement
Date" a day or three after the date the list gives it). A tax form may
instead print its tax year, the year before the January it was issued in,
beside "1098" or "tax". One that does not is moved to Manual Review rather
than filed. A document whose row is turned off on the page is left for the
next run and the run goes on.

If the bank answers as signed out, the run stops and keeps what it saved.
Sign in again and run Resume.

Files are named after the document's date and its kind.

- `YYYY-MM-DD Simmons Bank Loan Statement.pdf`, in Statements
- `YYYY-MM-DD Simmons Bank Notice - Prime Rate Notice.pdf`, the notice's
  own title without its month and year, in Notices
- `YYYY-MM-DD Simmons Bank Tax Reporting 2030.pdf`, the year the form
  reports, in Tax Documents

Only when a name is already taken does the file add six letters that tell
it apart. No account number or document id is ever in a file name.

Never touched are Accept, Enroll, OK, Notify, the filter menu, Apply, Clear
all, every navigation link (Dashboard, Messages, Accounts, Transfers,
Remote deposits, Bill pay, Zelle, Support), the links to other services
(Open a new account, Refer a Friend, Direct Deposit Switch), the user menu
and Sign out. Your user id, document ids, account ids, account number and
last four, your name, your email, your balances and your transactions are
kept out of every log, record, the index and every diagnostic file. A
record keeps a one-way hash of the document id, never the id.

## Not seen yet

- A Simmons account with deposit accounts or a second loan. The one
  account run had one loan, and the list stops when its documents name two
  accounts.
- The bank's sign-in page as the app meets it mid-run, and how long an idle
  session lasts.

The first run settled the rest. All 27 rows are drawn at once, the core's
press reaches a row's button through Banno's shadow roots, each press makes
the page ask the PDF's address once and the download lands under the
document's own file name, and the PDFs print their dates as numbers a day
or three after the list's date.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. One file drives a made-up page of the same shadow-root shape in
a real browser with the network refused.
