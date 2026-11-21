# Trade Republic statement downloader

Downloads your own **Trade Republic monthly account statements** as PDFs,
for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

**UNTESTED.** Built on 2026-11-20 without a Trade Republic account, so no
page and no statement has been seen here. Its routes were first seen in
the [Habeas sources](https://github.com/habeas-dev/sources) definition for
Trade Republic (`sources/traderepublic.json`, CC0, marked first-party and
verified). No code from it was used. If you have a Trade Republic account,
one Login, one Diagnose and one Pilot from you settle what is left, see
below.

## How it reads the site

Once you are signed in and the web app shows its home page
(`app.traderepublic.com/boards`), the app asks Trade Republic for one
month's statement at a time, from inside that tab, with the session you
signed in with. Each month is one request to `api.traderepublic.com` with
the month's first and last day, and the answer is the statement PDF itself.
About three years (1100 days) are kept. The month you are in is left out,
since its statement is not made yet. Nothing on the page is clicked, typed
or loaded, and a redirect is never followed.

A month is saved only when its PDF prints that month's first and last day,
as dates like `01.03.2026` and `31.03.2026`, and does not print a
neighboring month's. A PDF that shows another month, neither day, or no
text at all is never saved. That date form is a guess until someone runs
it, which is what Diagnose is for.

A month Trade Republic answers with no PDF (an empty answer, an error, a
page) is recorded as having no statement, said at the end of the run, and
asked again next time. It is never taken for a sign-out or for done. After
three such months in a row the newest months are asked again, and the run
goes on only while one of them still answers with a statement. A 401
or a 403 means you are signed out, and the run stops with that month left
for Resume. Login says Success only when a statement actually answered.

**Not covered.** Trade confirmations, tax reports and other per-trade
documents are reached through the web app's live connection (a
WebSocket), which this app never opens. One Trade Republic account per
config. The statement names no account to the app, so a second person
uses a config of their own (`--config`).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page, click **Trade Republic**,
   then **Continue**, then **Set up**. Back on Accounts, click
   **Trade Republic** to open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Your own Edge or Chrome opens with a separate profile. Sign in to
   app.traderepublic.com yourself, with your phone number, PIN and the code
   Trade Republic sends, until the home page shows. Leave the window open.
4. If you use a terminal, run `paperpull traderepublic login`. It says
   Success only when Trade Republic answered with a statement.
5. Back in Get help, click **Make the report** (Diagnose). It asks for the
   newest months once each and writes two files in the Trade Republic
   folder's `Diagnostics`. `survey-diagnose-<time>.json` and
   `diagnose-documents.json` hold the answer's status class, whether it was
   a PDF, its page count and length, whether this month's first and last
   day were found, and how many dates of each shape the PDF holds. Counts
   and yes or no only, with no text from your account in them, never a
   date, an amount, a name or an account number. Diagnose saves nothing
   and clicks nothing.
6. Back on the Trade Republic page, click **Try the newest few first**. It
   tries the newest three months.
7. Open the files you will send in Notepad and look through them. If
   anything in one looks personal, delete that line.
8. Open a [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
   for Trade Republic, or comment on the one that is open, and attach both
   Diagnose files, any `failure-*.json`, and what Login and the Pilot
   printed.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke, as counts and states, with no text from your account
in it. Attach it to the issue the same way.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, with your own phone number, PIN and code, and leave the
window open. The app never sees any of them.

## Safety

Trade Republic is a broker and a bank. This app activates no control at
all, never places an order, never moves money and never changes a setting.
It makes one GET a month to `api.traderepublic.com` from the signed-in tab
on `app.traderepublic.com`, and no other host. A tab that is not on the
home page stops the run with nothing asked.

## Commands

```
paperpull traderepublic setup
paperpull traderepublic login        sign in yourself, leave the window open
paperpull traderepublic diagnose     ask the newest months once, write counts to send
paperpull traderepublic discover     list the months in reach
paperpull traderepublic pilot        save the newest few months
paperpull traderepublic all          save every month in reach
paperpull traderepublic resume       carry on after a stop
paperpull traderepublic verify       recheck saved PDFs
```
