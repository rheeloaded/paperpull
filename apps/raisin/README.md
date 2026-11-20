# Raisin (Weltsparen) deposit document downloader

Downloads your own **Raisin deposit documents** from the Raisin dashboard
(raisin.com, Weltsparen in Germany), as PDFs, for your records. That means
the documents Raisin lists for each term deposit and overnight savings
account, such as statements, confirmations, contract documents and tax
certificates. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

**UNTESTED.** Built on 2026-11-20 without a Raisin account, so no Raisin
page, list or PDF has been seen here. The routes it uses were first seen
in [Habeas sources](https://github.com/habeas-dev/sources)
(`sources/raisin.json`, CC0, marked first-party and verified 2026-09-30).
Only those facts were used, no outside code. If you have a Raisin account
you can finish it in one or two rounds, see below.

## How it reads the site

You sign in to www.raisin.com yourself and leave your dashboard open. Its
address carries your customer number (`customer_id=BAC_...`). The app asks
Raisin's own API at `api2.weltsparen.de` for the same lists the dashboard
reads, from inside that tab and with the sign-in the page already holds.

1. Your active deposits and your ended ones.
2. For each deposit, its documents, each with an id, a date, a title and a
   type.
3. For each document, its PDF.

Nothing on the page is clicked, typed or submitted, and the app goes to no
other page. Every request is a GET to one of four routes there. The page's
sign-in token stays in the page. It is never handed to PaperPull, so it is
in no log, failure file, Diagnose or Support report. Your customer number
is kept only as a digest in PaperPull's records on this computer.

A document is known by its id under its deposit, so two documents on one
day, or one id under two deposits, stay apart. Statements land in
`Kontoauszuege\`, tax certificates in `Steuerbescheinigungen\`, contracts
and confirmations in `Vertragsunterlagen\`, anything else in
`Sonstige Dokumente\`.

**Every PDF is checked before it is filed.** It must name Raisin or
Weltsparen and print its own date, day first (05.03.2026 is the fifth of
March, and an English 5 March 2026 is read too), and when another
document of the run carries the same date, its own title too. A PDF
that does not is not saved. It is said as unreadable,
unconfirmed or wrong, and the next run tries it again. This is stricter
than it may need to be, on purpose. If your documents name only a partner
bank, or print their date another way, every one is refused until your
first run says what they print, and that is a one-line repair. A
timestamp is taken as the day it was in Germany.

What is not known yet, and what your first run confirms.

- Where the deposits answer keeps its entries (`DEPOSIT_LIST_KEYS`).
- The locale the dashboard sends (`LOCALE`).
- Who a document names as its issuer (`ISSUER_WORDS`).
- How a document prints its own date (`DATE_FORMS`).

Each is a named constant in `raisin_site.py`.

**What it does not cover.** The Raisin cash account's transactions are data,
not documents. Raisin's sites for other countries, and Raisin in the United
States, may use other hosts, which the app refuses, or print their dates
in a way it does not read, in which case every PDF is refused until a
tester says how. A list that comes in pages stops the run rather than be
read as all of it, since no paging was recorded for these routes. One
document listed under two deposits is kept as two, the same file saved
under each.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page, click **Raisin**, then
   **Continue**, then **Set up**. Back on Accounts, click **Raisin** to open
   its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Your own Edge or Chrome opens with a separate profile. Sign in to
   Raisin yourself, answer any code it sends, open your dashboard (the page
   that lists your deposits) and leave the window open.
4. Once you are signed in, PaperPull checks the sign-in by reading your
   deposits list. It says signed in only when that list answered.
5. In Get help, click **Make the report**. This support report reads the
   lists and writes two files in the Raisin folder's `Diagnostics`.
   `survey-diagnose-<time>.json` is the one to send. It holds counts and
   states and no text from your account. `diagnose-documents.json` says how
   many deposits of each kind and documents were listed, how each request
   answered, whether the page held a sign-in, and the shape of each answer
   (its fields and how many entries each list held, never a value). Any
   word in it that is not on PaperPull's fixed list, a field name
   included, is written as its shape, a for a letter and 9 for a digit, so
   it can be sent too. If a list stopped, you may be asked to name one or
   two field names from your browser yourself. Diagnose downloads nothing, clicks
   nothing and takes no screenshot.
6. Click **Back to Raisin**, then **Try the newest few first**. It saves
   the three newest documents, or says why each was not saved.
7. Open the files you will send in Notepad and look through them. If
   anything in one looks personal, delete that line.
8. Open an issue titled Raisin on
   [GitHub](https://github.com/rheeloaded/paperpull/issues/new/choose) and
   attach the survey file, `diagnose-documents.json` and the Pilot's
   failure file if it wrote one, with a sentence about what your dashboard
   lists. If a PDF was refused as unconfirmed, say what it prints as its
   issuer and its date, in words like "Raisin Bank AG" and "05.03.2026",
   never the document itself.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts
and states, with no text from your account in it. Attach it to the issue
the same way.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, answer your own two-step code, and leave the window open.
The app never sees your password.

## Safety

This account moves money. The dashboard can open, extend and end
deposits, transfer to and from your reference account, and change your
personal and tax details. This app activates no control at all. It asks
for the deposit and document lists and the PDFs in them, every request a GET to
`api2.weltsparen.de` from your own tab. An expired session stops the run
rather than reporting an empty success.

## Commands

```
paperpull raisin setup
paperpull raisin login        sign in yourself, leave the window open
paperpull raisin discover     list every deposit's documents, download nothing
paperpull raisin pilot        the newest three
paperpull raisin all          everything, delete-safe on a rerun
paperpull raisin verify       re-check every saved PDF
paperpull raisin diagnose     counts and shapes, for a tester to send
```

## Tests

```
python -m pytest tests -q
```
