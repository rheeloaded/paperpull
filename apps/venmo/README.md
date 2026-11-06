# Venmo monthly statements

**Built and run on one account.** On 2026-10-13 a full run on one personal
account saved 24 monthly statements, October 2024 to September 2026, two
of them busy months whose "Show more" was pressed until every transaction
was drawn. Every point not yet seen on a second account is marked
`UNCONFIRMED` in `venmo_site.py`, where the app stops rather than guesses.

Venmo has **no PDF statement** on the web. Its Statements page shows one
month's account statement as a web page, with a "Download CSV" button.
This app opens each finished month's statement page by its own address and
prints it to PDF, filed as `<month end> Venmo Statement.pdf`, for example
`2026-09-30 Venmo Statement.pdf`. Where Venmo shows a month in Wallet and
Balance tabs, the Balance tab is saved as its own file,
`2026-09-30 Venmo Balance Statement.pdf`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Venmo**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer the code Venmo texts or emails you, and leave
   the window open. Then open **Statements** from the menu on the left.
4. Click **more** under the buttons, then **Diagnose**. It opens the
   Statements page, and the last two finished months by their own
   addresses, and writes `Diagnostics\diagnose-documents.json` in the
   Venmo folder. It saves no statement, clicks nothing, takes no
   screenshot, and writes any word that is not on PaperPull's fixed list
   as its shape. Addresses are written as their path and the names of
   their fields, never the values, so your profile id is not in it.
5. Click **Record**, in the same **more** menu. Go back to the browser window
   and click your way to last month's statement the way you normally
   would (do not press Download CSV or Send to email), then come back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough, written
   for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and month names, no
   usernames, names, amounts or notes. If anything in it looks personal,
   delete that line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach both files to a
   [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
   for Venmo, with a sentence about how you choose a month on the
   Statements page.
8. Click **Pilot**. It saves last month's statement as a PDF in
   `Statements\`. Open it and say whether it shows the whole month, then
   attach a fresh Diagnose file. If it then says months older than two
   years were not listed, choose "Between two dates" under "Which dates"
   and set a From date before your next run.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to the issue the same
way.

## Setup, for a checkout

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself on port 9295.
   Leave the window open.
4. Run `paperpull venmo diagnose`, then, once the site layer is confirmed,
   `paperpull venmo pilot` (one statement).
5. Check the downloaded statement before using `paperpull venmo all`.

## How it works

The app opens Statements by its address, which
Venmo settles on your profile's own statement address, and reads your
profile from it (the profile id is kept out of every file and log). Then,
newest first, it opens each finished month by that address with the month
and year changed, back to your start date. With no start date it reads
two years, and when the oldest of those months has transactions the run
saves those months as usual and then ends as a run that stopped, rather
than call the list complete, since older months may have them too. A
Resume after it does not call the run finished either. To read further
back, choose "Between two dates" under "Which dates" and set a From date,
or set `default_start_date` in `config.json`, and the walk goes back to
that date. A run of one year walks back to that year's first day. A month is listed,
and later printed, only when the address still names that month, the
month picker shows exactly that month, an "Account Statement" heading is
drawn, nothing is still loading, and either the month's transaction rows
are drawn, the same on two reads in a row, or Venmo's own words for a month
with none are, unchanged for two seconds. Venmo has two sentences for that,
"No transactions yet for this month" and "There are no transactions for
these dates", and which one you see goes by your own account. When the page's own
request for the month's transactions is heard, an answer that says more
are to come stops the month, and one that says signed out stops the run.
The month still under way is left out, since its statement is not final
yet, and so is a month with no transactions (counted only in the log). A
busy month draws ten transactions at a time. Before printing, the app
presses that month's own "Show more", and nothing else, until every
transaction is drawn, each press required to draw more and at most 60
presses. A "Show more" that Venmo has turned off is not pressed, and that
month is left for review and the next run. Nothing is printed while the
newest answer heard for the month says more transactions are to come. The
number of transactions printed is kept in the month's record.
Each statement remembers a one-way tag of the profile it was listed on.
If the browser is later signed in to another Venmo profile, the run stops
and prints nothing.

Some accounts get a newer Statements page, where a month has a Wallet tab and,
with a Balance account, a Balance tab. Only the open tab is on the page, so
the app reads both, opening the Balance tab by its address with nothing
pressed. Each tab that holds transactions is saved as its own statement, and a
month counts as empty only when neither does. "No transactions yet for this
month" on the Wallet tab is not enough on its own, since that page also says
it when Venmo could not load the month, so it counts only when Venmo's own
answer for the month says the same. The Balance tab shows a month's first ten
transactions, and its "Show more" does nothing, so a busier Balance month is
left for review rather than saved with some missing. Venmo's server normally
says whether an account has tabs, and the app takes its word. When it says
nothing, the page can learn of them a moment after it has drawn, so that month
waits up to five seconds for them, and tabs that first appear after months read
without them stop the list rather than leave those months unread.

A page the app cannot read whole stops the run rather than being called
complete. That is a month the page will not show as asked, a "Load more"
control on a month, a business profile, a month that never finishes
drawing, a month that shows neither transactions nor either sentence, as
one does when Venmo could not load it, a month that holds only pending
transactions, a Wallet tab saying it is empty when Venmo's own answer does
not say so or could not be read, or a Balance tab that does not open when
Venmo's answer does not say there is no Balance account. The run says which
month it stopped on. If Venmo answers as
signed out, the run stops and keeps what it saved. Sign in again and run
Resume.

## Validation status

Built 2026-10-13 from a read-only survey of a signed-in account, then run
on that account. Discover listed 24 months, Pilot saved one, and a full
run saved the other 23 (a Chrome tab crash midway was carried on with
Resume). Every PDF holds the whole statement, and the two busy months
printed 12 and 11 transactions with no "Show more" left. Not yet seen are
the following.

- "There are no transactions for these dates" on a live account. The app
  knows it from Venmo's own page code.
- The page with Wallet and Balance tabs on a live account. All of it comes
  from Venmo's own page code, and it stops rather than guesses at what that
  code does not show, which includes whether a visit can name the Balance tab
  in its address. A failure file or a Diagnose from such an account would
  settle it.
- How far back Venmo's statements go past two years. A month before the
  account opened shows the same "No transactions yet" as an empty month,
  so it is skipped, and with a start date the walk goes back to it.
- A month busy enough to need many "Show more" presses (at most 60 are
  made, and each must draw more).
- What a signed-out visit or answer looks like.
- Tax documents (1099-K), which are not listed. The surveyed account had
  none.
- A business profile, which is not listed.

**The CSV is never taken.** No PaperPull app keeps a CSV. The core's
download capture, file names, checks and Rename all take a PDF, so
keeping the CSV would be a change to the core first.

Never touched are paying, requesting, sending, splitting or transferring
money, Transfer balance, adding money, banks and cards, crypto, business
profiles, Send to email, Go paperless, privacy, notifications and
settings, and Log out. Your profile id, username, display name, email and
phone are kept out of every log and diagnostic file. The printed PDF is
your own statement and holds what it holds.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. `tests/test_a_month_with_no_transactions.py` and
`tests/test_a_statement_in_two_tabs.py` drive a real browser on made-up pages,
and nothing they do reaches Venmo. The others need no browser.
