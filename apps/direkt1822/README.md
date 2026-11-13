# 1822direkt

Downloads the PDFs 1822direkt already holds in its Postbox, account and
card statements, securities documents, tax certificates and other Postbox
documents, from Posteingang, Gesendet and the Papierkorb. Requested in
[#174](https://github.com/rheeloaded/paperpull/issues/174) and contributed
by [@MelleD](https://github.com/MelleD) in
[#213](https://github.com/rheeloaded/paperpull/pull/213). Its CDP port is 9314.

**Run on the contributor's own account on 2026-11-12**, with the build as
it was contributed, which could open conversations when asked to. A Pilot
saved five documents as valid PDFs, and a second Pilot saved nothing new.
This version never opens a conversation and has not been run on an
account yet. A whole run of the account has not been reported either.

## Commands in a checkout

`--root ./apps` picks the app in this checkout even when the panel is set
to use another install folder.

```sh
./paperpull --root ./apps direkt1822 login
```

Sign in yourself, answer your own two-factor prompt, and leave the window
open. The sign-in page is `https://www.1822direkt-banking.de/ng-banking/login/eingabe`
and the Postbox is at `https://www.1822direkt-banking.de/ng-banking/banking/postbox`.

```sh
./paperpull --root ./apps direkt1822 discover
./paperpull --root ./apps direkt1822 pilot
./paperpull --root ./apps direkt1822 all
```

Check the Pilot's PDFs first. Resume carries on with a run that stopped,
and Verify checks the saved PDFs on this computer. The bank may end a
session. Sign in again yourself and run Resume, and what was saved before
is remembered and skipped.

## Conversations are never opened

1822direkt opens a conversation only through `leseUndVermerkeMitId`, and
that call also marks it read at the bank, so this app never makes it. A
conversation's row in the list often offers a PDF of its own, and that PDF
is saved. A thread of more than one message may hold further attachments,
and a message with no PDF of its own may hold a text or a file, and
neither is read. Discover and the run summary say how many of each were
left unopened, so you can open them in the Postbox yourself.

## How it reads documents

- The signed-in page asks the Postbox's own JSON API for the lists and the
  files, from the bank's own address. Its `benutzerInfo` answer prepares
  the same `X-JOBA-AUTH` and `X-CSRF-TOKEN` headers the bank's own page
  sends. The tokens stay in the browser and are never written to a run
  file.
- Posteingang, Gesendet and Papierkorb are read with no account, category,
  date or unread filter. Setting `include_trash` to `false` leaves the
  Papierkorb out. Nothing deleted is restored.
- Pages are read from zero to the total the bank declares. A missing
  field, a page given twice, a total that changes or a history that stops
  short stops Discover before any of the list is recorded.
- A PDF is fetched from the address the bank's own page uses for it.
  Redirects are refused, and the bytes must start as a PDF does.
- The bank's category codes say which documents are account and card
  statements, securities documents and tax certificates. Any other kind
  is named by title rules or filed under Other Document.
- A second customer relationship under one sign-in is not mapped yet and
  stops Discover with that said. Several accounts of one customer are all
  in the one Postbox.

No control is pressed. Only the three folder lists, `benutzerInfo` and the
PDF download are asked for. Payment, transfer, trading, signing,
activation, delete, restore, settings and read-marking calls are never
made.

Documents are told apart as DKB's are, by kind, date and the whole title,
and a stored id is a hint the list is checked against. Documents alike
that cannot be told apart fail rather than be saved as each other. A
document whose PDF does not come (an HTTP error for that one file, a 401
or a 403 included, or an answer that is not a PDF) fails alone once the
list read again still answers, and the next run asks for it again. A list
that answers as signed out stops the run. A timestamp with a zone is filed
under its day in Berlin. Progress and indexes stay on this computer, and a
document saved once is remembered even after its file is deleted.

## Development checks

```sh
python -m pytest apps/direkt1822/tests -q
```

The in-page tests run the app's own page script against made-up answers,
in Node for each part of the list and in Playwright's Chromium for whole
runs. They check paging, the three folders, that tokens stay in the page,
that no conversation is opened, downloads, an ended session and a list
that stops short. No account is used. Diagnostic files and recordings are
kept out of Git.
