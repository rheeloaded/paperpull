# Spectrum Internet and Mobile statement downloader

Spectrum Internet statements, about a year of them, from Billing, then Statements, at
www.spectrum.net. That is the current account's, and the older account's after an account transfer.
Spectrum Mobile statements too. The site has no PDF for them, so each finished one is printed from
its own page.

Sign in yourself with `login.bat` / `login.command` (the browser opens on port 9291 with its own
profile), answer any one-time passcode yourself, and keep the window open. Then Discover, Pilot
(one statement) and Run All.

## How it works

The app opens Statements by its address and reads the list the page's own request gets back. The
newest statement's page is opened by its address. Every older statement is chosen the way a person
would, by pressing its own row on Statements, because a page opened by address for an older
statement prints the newest one instead. The app checks the page it moved to is that very
statement's, then presses "View Printable Statement" once. The page builds the PDF in the browser,
and the app keeps it only when the PDF the page received was asked for that statement, the PDF it
built holds the same bytes, its text prints the statement's date, it is not the same file as a
statement already saved, and no tab opened and no download began. Anything else stops the run. Two
statements of one date (one for each account, after a transfer) have rows nothing on the page tells
apart before a press, so the app presses the first, and if that opens the other account's statement
it goes back to Statements and presses the second, which must open the one it wants.

For Mobile the app opens Billing, presses "Mobile Account Number", presses the finished statement's
own row ("Statement August 13, 2026"), presses "Expand All", checks the page reads that date and
"Mobile", and prints the page to `2026-08-13 Spectrum Mobile Statement.pdf`. The statement still
under way, "Your Total So Far" and device orders are never pressed, and neither is the page's own
Print button. When the Mobile list cannot be read whole, Discover keeps the Internet statements it
listed and stops rather than call the list read.

## Read-only

A statement's own row and "View Printable Statement" for Internet, and the Mobile Account Number
link, a Mobile statement's row and its Expand All for Mobile, are the only controls the app will
press. Each is checked by name first, and a row is refused when its words mention paying, Auto Pay,
paperless, equipment, settings, signing out and the like. A row or link is pressed only when its own
address leads nowhere or stays on www.spectrum.net with none of those words in it. It never pays,
never touches Auto Pay, paperless, equipment, service or settings, and never types anything. If
Spectrum signs you out or asks for a one-time passcode, the run stops, keeps what it saved, and asks
you to sign in (or answer the passcode) and press Resume.

## Privacy

Account numbers, the service address and Spectrum's statement ids (which contain the account
number) are kept out of every file, log and diagnostic. Files are named by date, for example
`2026-09-26 Spectrum Internet Statement.pdf`. A prior account's statement adds "Prior Account", so
two statements of one day get two names.

## Status

Internet statements were run on the account owner's own account. Discover listed 13 statements of
two accounts, Pilot saved the newest, and Run All saved 10 more and refused the two of one date,
which are now chosen row by row but have not yet been run live. For Mobile a live run listed all 12
statements and opened each one's own page, and a whole Mobile run is still to come.

## Tests

Run `python -m pytest -q tests` with PaperPull's bundled Python.
