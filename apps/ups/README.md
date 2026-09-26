# UPS Billing Center invoice downloader

Downloads your own **UPS shipping invoices** from the UPS Billing Center,
as PDFs, for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

Mapped and run against the maintainer's own Billing Center account on
2026-09-25. Both invoices it lists were saved, each checked against its
own date and amount, and a second run downloaded nothing.

## How it reads the site

Invoices live in the **UPS Billing Center** at `billing.ups.com`, under
**My Invoices**. The page fills its table from UPS's own API, and every
call carries session headers only the page holds. So the app opens My
Invoices, keeps the list the page receives and the headers it sent, and
asks for each invoice's PDF exactly the way the page's own code does.
Nothing on the page is clicked.

An invoice is identified by the id UPS gave it. The invoice number
carries your account number inside it, so filenames use the date
instead, like `2026-02-14 UPS Shipping Invoice.pdf`.

**What it does not cover.** Supporting documents (freight bills,
brokerage and import forms) and the CSV and XML versions of an invoice.
Receipts in Shipping History on ups.com belong to shipments made from
that login and are a different system.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in to ups.com yourself, answer your own code, and leave the window
open. The app opens the Billing Center from there. It never sees your
password.

## Safety

The Billing Center takes payments. It can pay invoices, set up automatic
payments, dispute charges, change plans and email invoices. This app
activates no control at all. It opens My Invoices, keeps what the page
receives, and asks for invoice PDFs, every address on `ups.com`. An
expired session stops the run rather than reporting an empty success.

## Commands

```
paperpull ups setup
paperpull ups login        sign in yourself, leave the window open
paperpull ups discover     list what the Billing Center has, download nothing
paperpull ups pilot        the newest five
paperpull ups all          everything, delete-safe on a rerun
paperpull ups verify       re-check every saved PDF
paperpull ups diagnose     survey the list, for when it changes
```

## Tests

```
python -m pytest tests -q
```
