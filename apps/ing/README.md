# ING (ING-DiBa) document downloader

Downloads the PDFs in your ING **Postbox**, the bank's document inbox, and in
its archive, for your records. Kontoauszüge, Kreditkartenabrechnungen,
Wertpapierdokumente, Steuerbescheinigungen, Vertragsinformationen and
Mitteilungen. Read-only, delete-safe, and part of
[PaperPull](../../README.md). Contributed by
[@MelleD](https://github.com/MelleD) in
[#203](https://github.com/rheeloaded/paperpull/pull/203), built after the
[DKB](../dkb) app and requested in
[#169](https://github.com/rheeloaded/paperpull/issues/169).

**Status. Tested on one contributor's real ING account from the command
line.** A full run saved documents and a pilot after it saved no new files.
A populated archive and some document types have not been checked, and no
run from the panel on a real account has been confirmed yet. The app was
first written from public descriptions of the Postbox (see
[Sources](#sources)), and its automated tests run against an invented page.
Where ING's page differs from what the app expects, a run stops and says
what it did not find, rather than guess or report an empty success.

## How it reads the site

After sign-in the browser is on ING's web banking at `banking.ing.de`. The
app reads two lists there, the Postbox (`/app/postbox/postbox`) and its
archive (`/app/postbox/postbox_archiv`), as the rows the page shows, each
row's document type, subject, date and download link. A row is filed by the
words of its document type, or, when the type names only a message or
nothing below, by its type and subject together. The first line that
matches wins.

| Words in the row (German or English) | Folder | `document_types` entry |
|---|---|---|
| Steuer, Freistellung, Verlust- or Jahresbescheinigung, Erträgnis | `Steuerbescheinigungen` | `Tax Document` |
| Kreditkarte, VISA | `Kreditkartenabrechnungen` | `Credit Card Statement` |
| Depot, Wertpapier, Dividende, Ausschüttung, Kauf, Verkauf, Sparplan, Kosteninformation, Fonds | `Wertpapierdokumente` | `Securities Document` |
| Kontoauszug, Girokonto, Tagesgeld, Rechnungsabschluss | `Kontoauszuege` | `Statement` |
| Vertrag, Bedingungen, Preis- und Leistungsverzeichnis, Vereinbarung, Kontoeröffnung | `Vertragsinformationen` | `Contract Information` |
| Mitteilung, Information, Schreiben, Brief | `Mitteilungen` | `Message` |
| anything else | `Sonstige Dokumente` | `Other Document` |

The app never clicks, types or submits anything in the Postbox. Each time
it lists, it opens the two list addresses itself, even when the Postbox is
already on screen, so a search or filter you left set in the window is not
read as the whole list. It waits for the rows to settle, scrolls the list
so rows that load on scrolling appear, and reads them. Each PDF is fetched
with a GET from inside the signed-in page, so the session cookies never
leave the browser. ING's download links carry the page they were read from,
and may name a row by its place in the list, so a document's link is read
again from its list, opened afresh by its address, just before the PDF is
fetched. A document arriving during a run cannot then move a later link
onto its neighbor. When ING answers with a page instead of the PDF, as it
may for a link that has expired, the list is opened again and the fresh
link fetched once more. When that fails too, the document is marked failed and the next
run tries it again. A ZIP holding one PDF is unpacked, and anything else in
a ZIP is kept for manual review.

A list is read whole or not at all. A run stops, and says which list and
why, when a list is still loading, has a further page or a "show more"
button (the app presses neither), shows more than 5000 rows, shows rows but
none the app reads, shows no download link in any row (it may sit in a
menu, which the app does not open), or has no row with a date it can read.
Nothing read is then taken as the whole list. It stops the same way when
ING shows its sign-in page.

Column headings are not document rows. A list with no document rows shows
ING's notice that nothing matches, "Zu Ihrer Suche können keine Dokumente
angezeigt werden", in the list's own box. ING shows the same notice for a
search or filter that finds nothing, so the app never takes it to show a
list empty. A list that shows only the notice is left out and named. The
run takes the other list's documents, records nothing against a document
listed before from the list left out, and stops at its end rather than
finish, as a run whose list was not read. A later run takes that document
once its list shows it again. If your archive is empty in ING, set
`read_archive` to `false` and runs leave it out. If the Postbox shows only
the notice, look at its search and filters in ING. The same words anywhere
else on the page, a count, or "keine neuen Nachrichten" (no new messages,
which is not no messages) are not taken for the notice. The app opens each
list by its own address, which is expected to clear a search or filter,
but whether ING keeps a filter for the whole session has not been checked.

Some rows are passed over, and Discover says how many and why. These are
rows the Postbox marks unread when `include_unread` is `false`, rows with
no download link, with more than one, or with one the app does not follow,
and rows without a date in the form `dd.mm.yyyy`, which includes rows dated
"Heute" or "Gestern". Nothing is saved for them. Open them in the Postbox
yourself.

Each document is identified by its kind, its title, the last four digits of
the account, depot or card it names, and its date, never by its link, which
changes with every page. Documents alike in all four are told apart by their
order in the list only while the list shows as many of them as Discover
found. When it does not, that document is marked failed with the reason
rather than guessed. File names carry the date, a fixed name for the kind,
such as `Kontoauszug`, and the last four digits of the account, depot or
card, never the whole number and never the subject.

**Options** in `config.json`.

- `document_types`, which kinds a run downloads, all seven by default. Drop
  the ones you do not want, for example keep only `"Statement"` and
  `"Tax Document"`.
- `include_unread`, `true` by default, so rows the Postbox marks unread are
  downloaded too. Whether downloading an unread document marks it read in
  ING has not been checked on a real account, and it may. Set this to
  `false` to leave unread rows alone.
- `read_archive`, `true` by default. `false` reads the Postbox only. Set it
  to `false` when your archive is empty in ING, since an empty archive shows
  only ING's notice that nothing matches, and every run that reads it then
  stops at its end.
- `pilot_count`, how many documents a pilot downloads, 5 by default.
- `delay_min_seconds` and `delay_max_seconds`, the pause between documents.

## Sign-in

You sign in yourself in your own Edge or Chrome, in a separate profile, and
complete any confirmation in the ING app yourself. The app never sees your
password and never confirms anything. The launcher opens ING's
[official banking entry](https://banking.ing.de/app/obligo), which redirects
to the sign-in page. Open the Postbox once you are signed in, and leave the
window open.

## Staying signed in

How long ING keeps a session that only a run uses has not been checked. When
ING shows its sign-in page, or answers a download as signed out, the run
stops and says so, and everything saved so far is kept. Sign in again in the
open window and run Resume, which carries on where it stopped. The app does
not keep the session alive behind the bank's back.

## Safety

This is a bank account, and may hold a credit card and a securities account.
The site can transfer money, set up standing orders, buy and sell
securities, change limits and lock cards. This app activates no control at
all. It reads the rows of the two Postbox lists and fetches their download
links. A link is fetched only when it is `https` on `banking.ing.de` under
`/app/`, and never when its address carries a word of an action, such as
logout, delete, archive, move, mark read, unread, transfer, payment,
setting, cancel or lock, in German or English, as written or decoded. The
in-page request refuses any other host before it is sent, sends only GET,
and refuses an answer that was redirected to another host. An expired
session stops the run rather than reporting an empty success.

## Limits

The single-account test does not cover every case.

- The row, cell and link structures and ING's document-type words have been
  checked on one account only, and not all document types have been seen.
- Whether downloading an unread document marks it read (hence
  `include_unread`).
- A populated archive. An empty archive has been seen. It shows only ING's
  notice that nothing matches, so a run that reads it stops at its end, and
  `read_archive: false` leaves it out.
- An empty list cannot be told from a search or filter that finds nothing,
  since ING shows the same notice for both. An empty Postbox stops every
  run at its end until a document arrives.
- Whether ING keeps a search or filter set in the Postbox after the list's
  own address is opened again.
- A list with paging or a "show more" button stops the run, since nothing is
  pressed. A download link inside a menu is not followed.
- A link that ING sends on to another host fails.
- A document listed identically in both the Postbox and the archive is
  saved twice.
- When one of two documents alike was saved and the other failed, later
  runs mark the other failed rather than guess which it is.
- A repeated pilot saved no new files on the one account. Other document
  sets have been tested only against invented pages.

## Local test before a PR

From the repository root on macOS, with a Chromium-based browser installed.

```bash
# Once, if the checkout has not been set up:
./setup-all.command

# Do not overwrite an existing personal config.
[ -e apps/ing/config.json ] || cp apps/ing/config.example.json apps/ing/config.json
```

In `apps/ing/config.json`, set `owner`, and set `output_dir` to the full path
of a folder outside the checkout, such as `/Users/you/Documents/ING-Test`
(`~` is not expanded), so no statement, log or run file is written into the
repository. For the first test, set `pilot_count` to `2`. Then follow these
steps.

1. `./paperpull --root apps ing login` opens the browser. Sign in yourself,
   open the Postbox, and leave the window open.
2. `./paperpull --root apps ing diagnose` looks at the Postbox on screen
   without moving, scrolling or clicking anything, and downloads nothing. It
   prints how many rows it found, with a readable date and with a download
   link, and how many a run would read and why the rest are left out.
3. `./paperpull --root apps ing discover` reads the Postbox and the archive
   and lists what a run would download, downloading nothing. Compare its
   count with what the Postbox shows. When your archive is empty in ING,
   set `read_archive` to `false` first, or Discover lists the Postbox and
   then stops, since an empty archive shows only ING's notice that nothing
   matches.
4. `./paperpull --root apps ing pilot` downloads the newest two. Open the
   PDFs and check that they are the right documents, in the right folders.
5. Run `pilot` again. It must say "Already downloaded and verified" for both
   and save nothing new.
6. `./paperpull --root apps ing all`, then compare the folders with the
   Postbox and the archive.

Optionally, to answer whether a download marks a document read, when the
newest document in the Postbox is unread, set `pilot_count` to `1`, run
`pilot`, and see whether ING now shows it as read.

When a step stops, its message says which list and why, and it writes a
`failure-*.json` of counts and states to `Diagnostics` in the output folder.
Send the message, that file and the output of `diagnose`, run with the list
in question open in the browser. Diagnose shapes every word that is not on
PaperPull's fixed list, `a` for a letter and `9` for a digit, so it shows no
subject, name or number. It also writes `Diagnostics/diagnose-documents.json`
in the output folder. Read them all through before sharing them.

When the page needs mapping again, `./paperpull --root apps ing record`
records the navigation you choose after it starts. Open the Postbox, the
archive and one PDF yourself, then press Enter. Opening a message yourself
may mark it read in ING. It writes `Diagnostics/recording.json` in the output
folder, with shaped addresses, query-parameter names, methods and statuses
for HTML navigations and requests, but never query values, HTML bodies or
form contents. If Record says its request limit was reached or that an
answer could not be recorded, the file may be incomplete. Save it before
starting another recording, which otherwise replaces it.

Record and Diagnose shape or redact data, but cannot guarantee that every
personal detail is removed. Never commit them, your browser profile, config,
PDFs, credentials or account data.

Run the automated checks, one suite per pytest process.

```bash
(cd apps/ing && ../../gui/.venv/bin/python -m pytest tests -q)
gui/.venv/bin/python -m pytest core/tests/test_every_app_guard.py -q
gui/.venv/bin/python -m pytest gui/tests/test_provider_cards.py -q
git status --short --untracked-files=all
```

## Commands

```
paperpull ing setup
paperpull ing login        sign in yourself, open the Postbox, leave the window open
paperpull ing diagnose     look at the Postbox on screen, download nothing
paperpull ing discover     list what the Postbox and archive have, download nothing
paperpull ing pilot        the newest five (pilot_count)
paperpull ing all          everything, delete-safe on a rerun
paperpull ing resume       carry on after a stop
paperpull ing verify       re-check every saved PDF
paperpull ing record       record your own way through the Postbox, for mapping
```

## Tests

```
python -m pytest tests -q
```

The automated tests run against an invented Postbox, including one in a real
headless browser. They show that the app reads what it expects and stops
where it should. The real-account test covers only one account.

## Sources

ING's [Postbox help](https://www.ing.de/hilfe/persoenliches/postbox/) describes
the inbox and archive. A public [Postbox downloader](https://github.com/LinusHoppe/ing-postbox-downloader)
describes the document rows in the page, but handles only the documents on
screen and uses browser clicks because programmatic downloads can fail.
Another [browser extension](https://github.com/et15/firefox_ing_mailboxdownload)
fetches links from the table on screen using the signed-in session. An
[additional userscript](https://github.com/Erzmaster/Unofficial-ING-Documents-Batch-Downloader)
tells an unread row by its class and clicks a row when its mark-as-read
option is turned on. None of them shows how to read the whole Postbox or
whether downloading alone changes a document's read status.
