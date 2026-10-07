# Vanguard statements

This provider reads documents from a browser where you sign in yourself.
Passwords and verification codes are never handled by the downloader.

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself.
4. Run `paperpull vanguard diagnose`, then `paperpull vanguard pilot`.
5. Check the downloaded documents before using `paperpull vanguard all`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## Validation status

Mapped and run against a real account (2026-09-28): a pilot saved 5 of 5,
a full run saved 135 statements across five accounts (2020-2026, including
an employer 401(k)), every one a valid PDF, and a second run downloaded
nothing. Uses current upstream core, standard launchers, a provider-local
Python environment, and a separate browser profile on port 9282.
Automated tests cover parsing, filing, document identity, browser
configuration, and request/control guards.

## How it reads the site

Sign-in is at `logon.vanguard.com`; the portal's documents shell at
`investor.vanguard.com/myaccount/documents` spawns the statements app on
its own host, `statements.web.vanguard.com`. Nothing there is clicked to
find a document: the app captures the same JSON call the page itself makes
(`lah-statements-consumer`, one response per year selected), which names
every statement with its account, period and a per-document id. Each
statement's PDF is then saved by clicking its own row's download control
(`title="Pdf download icon"` — the row's aria-labels carry non-breaking
spaces that defeat text matching, the title attribute does not) and
taking the file the browser saves, with the browser pointed first at
`.vanguard-downloads`, a staging folder in the output folder, given to the
browser as a full path, since a browser told a relative one cancels every
download. Once that folder is set, the browser's file there is the only
copy, since the download event's own copy is then empty, so the file the
download event names is moved into place under the app's name. Only that
file is taken and nothing else in the folder is touched, since a
download from another tab lands there too, and nothing is taken when the
download failed or never began. Where setting the folder has no effect, the
download event's own copy is saved instead.
Every account's statements arrive in one table, so the account filter is
never driven; the year picker is a native `<select>` whose options must
all be bare four-digit years before the app will touch it, and a year a
scoped run does not want is never selected — the picker walk skips it
rather than fetching its statements to drop them afterwards. Trade confirmations, tax forms and
letters are sibling apps on the same host and are reachable for a future
extension; this provider ships with statements, the documents the account
actually has today.

## Nothing is pressed under something else

No press is ever forced. The download icon, and the button that keeps a
session going, are brought to the middle of the window first and pressed
only when they are the thing on top at the point the press lands. When a
chat window, an offer or a banner sits over one, nothing is pressed, the
run stops and says what is over it in words from PaperPull's fixed list,
and a failure file is written. One that comes over the icon at the very
moment of the press does not get it when it is part of the page, since
Playwright's own check holds the press back, waits and tries again, and
the run stops only if it is still there when the press's time runs out. A
chat window drawn in a frame of its own is out of that check's sight and
can still take that one press, so the point is looked at again right after
the press, and the run stops there too. A press that brings no download at
all, or that the page does not answer in time, is not made again, and the
run stops there as well. Close whatever covers it in the browser window,
then press Resume in the panel or run `paperpull vanguard resume`.
