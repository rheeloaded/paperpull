# FedEx Billing Online invoice downloader

Downloads your own **FedEx shipping invoices** from FedEx Billing Online,
as PDFs, for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

**UNTESTED.** Built on 2026-09-25 from a real FedEx login whose shipping
account is not connected to Billing Online, so no invoice has been seen.
How Billing Online loads its data is known, from the app itself. What an
invoice row holds and how its PDF downloads are not, so the app reads rows
by looking for their fields. If you use FedEx Billing Online, you can
finish it in one or two rounds, see below.

## How it reads the site

FedEx Billing Online (`www.fedex.com/online/billing/`) loads its data from
FedEx's API with a token the page gets for itself. So the app opens the
invoices page and keeps every answer the page receives, picks out the
invoices, and saves each one from its own download link. Nothing on the
page is clicked. It pauses between invoices, since FedEx's bot protection
stops answering when asked too quickly.

**If your shipping account is not connected to Billing Online**, FedEx
shows a form asking for the account number. The app never fills it in. It
stops and says so, and connecting is yours to do in FedEx.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **FedEx**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to fedex.com yourself, answer any code it sends, and leave the
   window open.
4. Click **more** under the buttons, then **Diagnose**. It opens the
   invoices page and writes two files in the FedEx folder's
   `Diagnostics`. `survey-diagnose-<time>.json` is the one to send. It
   holds counts and states and no text from your account.
   `diagnose-documents.json` is the detailed one, with the shape of every
   answer the page received (field names and types, never a value) and
   the page's headings and button names, which can include your name or
   business, so it stays on your computer unless you are asked for it.
   Diagnose downloads nothing, clicks nothing and takes no screenshot.
5. Click **Record**, in the same **more** menu, then click your way to
   one invoice PDF the way you normally would, and come back and click
   **Stop recording**. It writes `Diagnostics\recording.json`, records
   nothing you type and reads no cookies. The whole walkthrough is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open the files you will send in Notepad and look through them. If
   anything in one looks personal, delete that line.
7. Attach the survey file and the recording to the FedEx issue on
   GitHub, with a sentence about how many invoices Billing Online shows
   you. If you are asked for the detailed file, read it through first
   and delete any line that names you or your business.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts
and states, with no text from your account in it. Attach it to the issue
the same way.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, answer your own code, and leave the window open. The app
never sees your password.

## Safety

Billing Online takes payments and disputes. This app activates no control
at all. It opens the invoices page, keeps what the page receives, and
fetches a PDF from an invoice's own link, every address on `fedex.com`.
An expired session stops the run rather than reporting an empty success.

## Commands

```
paperpull fedex setup
paperpull fedex login        sign in yourself, leave the window open
paperpull fedex discover     list what Billing Online has, download nothing
paperpull fedex pilot        the newest five
paperpull fedex all          everything, delete-safe on a rerun
paperpull fedex verify       re-check every saved PDF
paperpull fedex diagnose     survey the answers, for when it changes
```

## Tests

```
python -m pytest tests -q
```
