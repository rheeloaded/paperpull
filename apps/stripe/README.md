# Stripe fee invoice and tax form downloader

Downloads your own **Stripe fee invoices** and **tax forms** (1099-K and
the like) from the Stripe Dashboard, as PDFs, for your records. For people
who take payments through Stripe, directly or through a platform such as
Ko-fi. Read-only, delete-safe, and part of [PaperPull](../../README.md).

**UNTESTED.** Built on 2026-09-25 against a real merchant account that had
no invoices, tax forms or payouts yet, so every list was empty. How each
list is asked for is known, and so is what the Dashboard's own code reads
from an invoice row. What a tax form row holds is not, so the app reads it
by looking for its fields. If you have Stripe invoices or tax forms, you
can finish it in one or two rounds, see below.

## How it reads the site

The Dashboard loads its data with requests that carry the session's own
headers, which only the page itself holds. So the app opens two settings
pages, **Plans and fees, Invoice history** and **Compliance and
documents, My documents**, and keeps the list each page receives. A long
list is read to the end by repeating the page's own request. Each
document is then saved from its own download link. Nothing on the page is
clicked.

Fee invoices land in `Fee Invoices\`, tax forms in `Tax Documents\`. A
document is identified by the id Stripe gave it.

**What it does not cover.** Payouts, payments and balance reports are
data exports, not documents. A 1099 can sit behind a step that asks for
your tax ID. The app never answers that. It marks the form for manual
review and says to download it yourself in the Dashboard.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Stripe**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to the Stripe Dashboard yourself, answer any code it sends, and
   leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It opens the two
   list pages and writes two files in the Stripe folder's `Diagnostics`.
   `survey-diagnose-<time>.json` is the one to send. It holds counts and
   states and no text from your account. `diagnose-documents.json` is the
   detailed one. It keeps the shape of each list (field names, types and
   counts, never a value) but also the page's headings and button names,
   which can include your business name, so it stays on your computer
   unless you are asked for it. Diagnose downloads nothing, clicks
   nothing and takes no screenshot.
5. Click **Record**, in the same **more** menu, then click your way to one
   invoice or tax form download the way you normally would, and come back
   and click **Stop recording**. It writes `Diagnostics\recording.json`,
   records nothing you type and reads no cookies. The whole walkthrough
   is [Testing a provider](../../docs/testing-a-provider.md).
6. Open the files you will send in Notepad and look through them. If
   anything in one looks personal, delete that line.
7. Attach the survey file and the recording to
   [issue #53](https://github.com/rheeloaded/paperpull/issues/53), with a
   sentence about which documents your Dashboard lists. If you are asked
   for the detailed file, read it through first and delete any line that
   names your business.

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

This account moves money. The Dashboard can pay out funds, refund,
charge a card, create payments and invoices, change bank accounts, reveal
secret keys and regenerate invoices. This app activates no control at
all. It opens two settings pages, keeps what they receive, and fetches a
PDF from a row's own link, every address on `stripe.com`. An expired
session stops the run rather than reporting an empty success.

## Commands

```
paperpull stripe setup
paperpull stripe login        sign in yourself, leave the window open
paperpull stripe discover     list what the Dashboard has, download nothing
paperpull stripe pilot        the newest five
paperpull stripe all          everything, delete-safe on a rerun
paperpull stripe verify       re-check every saved PDF
paperpull stripe diagnose     survey the two lists, for when it changes
```

## Tests

```
python -m pytest tests -q
```
