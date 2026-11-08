# DKB (Deutsche Kreditbank) document downloader

Downloads every PDF in your DKB **Postfach**, the bank's document inbox, for
your records: Kontoauszüge, Kreditkartenabrechnungen, Wertpapierdokumente
(Depotauszüge, Wertpapier- und Ertragsabrechnungen), Steuerbescheinigungen,
Vertragsinformationen and Mitteilungen. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

**Status: built, not yet run against a real account.** Scaffolded on
2026-11-08. The API it reads is written from what the Postfach is known to
ask for and is marked UNVERIFIED in `dkb_site.py` until a signed-in survey
or recording confirms it.

## How it reads the site

After sign-in the browser is on DKB's web banking at `banking.dkb.de`. The
Postfach filters by six kinds, and the app files into one folder for each:

| Postfach filter | Folder | `document_types` entry |
|---|---|---|
| Kontoauszüge | `Kontoauszuege` | `Statement` |
| Kreditkartenabrechnungen | `Kreditkartenabrechnungen` | `Credit Card Statement` |
| Wertpapierdokumente | `Wertpapierdokumente` | `Securities Document` |
| Steuerbescheinigungen | `Steuerbescheinigungen` | `Tax Document` |
| Vertragsinformationen | `Vertragsinformationen` | `Contract Information` |
| Mitteilungen | `Mitteilungen` | `Message` |

The app never clicks anything in the Postfach. It makes the same GET calls
the page makes, from inside the signed-in page, so the session cookies never
leave the browser. One call lists the documents, one lists the messages for
their subjects, and one returns a document's PDF. It never sends the call
that marks a message read, archives it or deletes it.

Each document is identified by its title, its account and its date, never
by the Postfach's own id, which is stored as a hint and looked up fresh at
download time. File names carry the last four digits of the IBAN, depot or
card, never the whole number.

**Which kinds a run downloads** is `document_types` in `config.json`. All
six by default. Drop the ones you do not want, for example keep only
`"Statement"` and `"Securities Document"` for Kontoauszüge and Depot.

## Sign-in

You sign in yourself in your own Edge or Chrome, in a separate profile, and
confirm the login in the DKB app. The app never sees your password and never
confirms anything in the DKB app. Leave the window open.

## Staying signed in

DKB signs a tab out about six minutes after you last used it, and a run's
calls do not count as use, so a long run stops part way, or the page asks
"Banking weiter nutzen?". Answer that yourself, or sign in again and run
Resume, which carries on where it stopped. The app does not keep the
session alive behind the bank's back. With a pause of one second between
documents, `"delay_min_seconds": 1` and `"delay_max_seconds": 1`, a session
holds about two hundred documents.

## Safety

This is a bank account, a credit card and a securities account. The site
can transfer money, set up standing orders, buy and sell securities, change
limits and lock cards. This app never activates a control that does any of
those. Every control it would touch has to clear a blocklist of those words,
in German and English, and match an allowlist of document words. Every URL
it reads has to be on `dkb.de`, the in-page request refuses any other host
before it is sent, and it only ever sends GET. An expired session stops the
run rather than reporting an empty success.

## Commands

```
paperpull dkb setup
paperpull dkb login        sign in yourself, leave the window open
paperpull dkb discover     list what the Postfach has, download nothing
paperpull dkb pilot        the newest five
paperpull dkb all          everything, delete-safe on a rerun
paperpull dkb verify       re-check every saved PDF
paperpull dkb diagnose     survey the Postfach, for when it changes
```

## Tests

```
python -m pytest tests -q
```
