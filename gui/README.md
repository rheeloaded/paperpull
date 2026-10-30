# PaperPull control panel (GUI)

A small local web page that drives every downloader app. It lists every
provider and person with what needs you, and gets new documents with one
button per account. It only runs the same predefined commands the `.bat`
files do, and nothing from the page is passed to a shell.

![The Accounts page on the sample archive. Every name and amount is invented.](../docs/panel.png)

## Run it

```bat
run_gui.bat
```

That starts the server and opens <http://127.0.0.1:8765>. It listens on
localhost only. It runs on `gui/.venv`, the one environment setup-all builds
for the panel and every app, so in a checkout run `setup-all.bat` (or
`./setup-all.command`) once first. Without it, run_gui makes a small venv
with the panel's own packages, and the panel asks for setup-all before it
runs an app.

Needs **Python 3.11+**, the same floor as the rest of PaperPull.

Closing the browser tab stops the run it was showing. That is deliberate. A
downloader driving your signed-in browser should not keep going once
nothing is watching it. Nothing is lost, a document is only marked done
after it is saved, so the next run picks up exactly where this one stopped,
and the account's row says the run stopped partway.

Apps run from the panel get no stdin, so nothing can stop and wait for an
answer nobody is able to type. The welcome asks for the account holder's
name on the page instead, which is what fills the index CSV's **Account
Holder** column. To set it later, put `"owner"` in the provider's
`config.json`.

Or manually:

```bat
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
python -m uvicorn app:app --port 8765
```

The page itself is `static/index.html`, `static/app.css` and
`static/app.js`, with no build step. `app.py` puts the three together when
it starts.

## Which apps does it drive?

The first time it runs with nothing to show, the welcome asks where your
documents should go, then which providers you use, then whose documents
they are. A folder is set up for each provider you choose. If you already
have PaperPull folders from before, the welcome's **Already have PaperPull
folders?** points the panel at them. Nothing is moved or copied, and the
old way of running them keeps working alongside.

To change the folder later, open **Settings** and use **Your PaperPull
folder**.

The choice is saved outside the program folder, so upgrading the panel does
not lose it. On Windows that is `%APPDATA%\PaperPull\settings.json`, in
Roaming AppData. On macOS it is
`~/Library/Application Support/PaperPull/settings.json`, and on Linux
`$XDG_CONFIG_HOME/paperpull/settings.json`, or
`~/.config/paperpull/settings.json` when `XDG_CONFIG_HOME` is unset or empty.

Versions before 0.19.1 kept the Windows file at
`%LOCALAPPDATA%\PaperPull\settings.json`. When the panel finds a file there
and none in Roaming AppData, it moves it across. If the move fails, the panel
goes on using the file where it is.

Running from a checkout of the repo, it uses `../apps` unless told otherwise.
The `APPS_ROOT` environment variable overrides both of the above, which is
handy for development:

```bat
set APPS_ROOT=C:\path\to\Receipt and Statement Downloader
run_gui.bat
```

It finds any subfolder containing an entry script (`*_receipts.py` /
`*_docs.py`), so it works with either the `apps/<slug>` layout or the original
`Provider Name/` folders. Each app runs on its own `.venv` if it has one, and
otherwise on the panel's own Python, which setup-all gives what every app
needs.

## Accounts

The home page has one row per provider and person, most in need first. Each
row says where it stands in plain words and has one button for the next
step.

| Status | Means | The button |
|--------|-------|------------|
| Stopped partway | The last run that downloads ended early, a page closed, a sign-out, an error | Continue, or Get new when the last run was a Continue that stopped because no run had read the provider's whole list, which only a run that lists can carry on from |
| Needs a look | The last run set something aside, a document in Manual Review, a wrong document refused, a failure | See what to check |
| Overdue | The newest document is far past how often this provider sends one | Get new |
| New one likely | The newest document is past its usual date | Get new |
| Possible gap | Documents look missing in the middle of the history | Look for them, a run over those dates |
| Up to date, Checked | Nothing is past its usual date, or a receipt archive that was checked | Get new |
| Not started | Set up and never run | Start |

How current an archive is comes from `tools/status.py`, run on each
account's own folder, measured against how often that provider sends a
document. The panel never says an account is signed in, since nothing short
of a run can know that. When several accounts may have something new,
**Get new for all** runs them one after another, and pauses at one that does
not finish, so you can sign in again and try it once more, or skip it.

Each run the panel starts is noted in `panel-runs.json` in the account's
folder, the newest twenty, with how it ended and the names of the files it
saved. That is where a row's last run and an account's Recent runs come
from. A run started from a terminal is not in it, though its run summary
still counts as a check. Only one run of an account goes at a time. A
second, from another tab, is refused until the first ends.

## One account

Each provider and person has a page of its own. Everyday steps are on it,
the rest are under **More**, and every one says what it does.

| On the page | What it runs |
|-------------|--------------|
| **Open sign-in window** | Opens that provider's own browser (Chromium, or Edge/Chrome for bot-protected sites). **You** sign in and leave it open |
| **Get new documents** | Downloads everything you do not already have (`--all --yes`) |
| **Try the newest few first** | Downloads the newest few as a test (`--pilot`) |
| **Only check what's there** | Lists what the provider has and downloads nothing (`--discover`) |
| **Continue** | Shown after a run that stopped. Picks up where it ended (`--resume --yes`) |

| Under More | What it runs |
|------------|--------------|
| **Restore deleted files** | Fetches again files you deleted, for a year or a range, see below |
| **Rename existing files** | A preview of new names (`--rename`), then the rename (`--rename --apply`) |
| **Check saved files** | Re-checks every saved PDF (`--verify`) |
| **Make a support report** | Reads the page and writes a survey for an issue (`--diagnose`) |
| **Record steps for support** | Watches while you click to a document (`--record`), with Stop recording |
| **Add another person** | A second account on the same provider, with its own folder, sign-in window and history |
| **Remove from PaperPull** | Moves the provider's folder into Removed. Nothing is deleted |
| **Open folder** | Shows the account's folder on this computer |

A run's page leads with what it came to, "3 new documents saved", lists
the files, and keeps the full output under **Technical details**. A run
that wrote a failure file offers it right there, to attach to an issue.

## Which dates

**All dates** is the default. It walks everything, which is what keeps each
archive's history complete for the Accounts page. Pick **One year**, or
**Between two dates**, and every run that lists documents gets the matching
`--year`, `--start-date` and `--end-date`. On sites with a year picker (U.S.
Bank, Chase, Target RedCard, Wealthfront, Target, Amazon) a scoped run skips
the years outside its window, which is the difference between a
three-second check and a minute of clicking through a decade. The choice is
remembered in your browser, so glance at the hint under it before getting
new documents.

## Restore deleted files

Downloads are remembered for good, so a document is never fetched twice,
even after you delete its PDF, say once it is in paperless-ngx. To get such
files back, open the provider, choose **Restore deleted files** under More,
pick a year, or both a From and a To date, and choose every missing file in
those dates or just the newest few. The panel adds `--redownload` to that
one run. The app goes through every document in the range again, the ones
already downloaded included, and fetches again each one whose file is gone.

- Nothing is overwritten. A file you still have stays as it is, and the
  app may save a second copy beside it, under a name of its own.
- The provider is asked again for each document fetched, so a long range
  takes as long as the first download did.
- It needs a year, or both a From and a To date, so a whole history is
  never fetched again by accident. One date alone is not enough, since it
  leaves the range open at the other end.
- It is a dialog of its own and is never remembered, so the next Get new
  documents is an ordinary one.
- Continue never downloads again. When a restore stops partway, the panel
  says so, and its row offers to restore the rest. Restoring the same
  range again fetches again what the first run already restored, so choose
  the part of the range it did not reach.
- PaperPull Server does not offer it. A run there hands every file it saves
  to Paperless, which would get each of these documents a second time.

## Spreadsheets

**Purchases** writes `All Purchases.xlsx` beside your installs, every line
item from every receipt archive (Amazon, Target, Walmart, Gap, and any second
accounts), newest first, with an Orders sheet and a Summary of spend per
provider per year. Pick one provider for `Amazon Purchases.xlsx` and so on,
both accounts in the one file. Only providers with line items are offered.
It is built from the order history the apps already keep, so no PDF is
opened and it takes a second. **Show in folder** opens the file manager on
it. It is made fresh each time, so edit a copy, not this file. A CSV is one
choice away for anything that is not Excel.

**Bank transactions** writes `All Transactions.xlsx`, or one provider's,
from the statement PDFs on disk. One row per transaction, and a Statements
sheet that says whether each statement reconciles to its own printed
balances. The first build of a big archive takes a few minutes and shows its
progress. Each PDF is read once and remembered, so the next build takes
seconds. Only archives with PDFs on disk are offered.

## File names

The **File names** page shows the name your newest file would get, and
builds it from parts you add, remove and move, each with how many of your
own files carry it. Separator and date style are chosen by example. One
pattern covers every receipts provider or every statements provider, or one
provider can have its own. Saving renames nothing. It then offers to rename
the files you already have, a preview first, then the rename. The pattern
language stays editable under **Edit as text**, see
[docs/file-naming.md](../docs/file-naming.md).

## Moving to another computer

In **Settings**, **Export history** hands the browser a file listing each
provider and person here, their settings, and every document each one has
already downloaded. **Import a history file** on the other computer, or on
PaperPull Server, reads it and shows what it will do before anything is
written. Then it sets up each provider and person not set up there, with
their settings, and marks what they already downloaded, so none of it is
downloaded again. The welcome offers the same import before any provider is
set up.

- Folders, browser profiles, the browser and debugging ports always belong
  to the computer the file is imported on, whatever the file says.
- A provider or person already set up keeps its own settings and only
  gains the history. Nothing is ever taken out of a history, and each
  `progress.json` is backed up in its Backups folder before it is written.
- No sign-in, password or PDF is in the file. It does hold document titles,
  order numbers, totals and the account holders' names.
- Nothing is imported while a provider is running.

## On PaperPull Server

The same page, behind the server's password. Every sign-in happens in the
**sign-in window**, the browser on the server's screen. Open sign-in window
docks it beside the page, and the **Sign-in window** button at the top
opens it at any time, or in a tab of its own with Full screen. The header
says **New files go to Paperless** when the Paperless plug-in has a consume
folder to copy into. Folder buttons become downloads, and the documents
folder is the shared data folder, see [SERVER.md](../SERVER.md).

## Light or dark

Light by default, dark when the system asks for it. **Settings** can also
fix it to either, remembered in this browser only.

## Notes and limits

- **Signing in is yours.** The panel opens the browser, and you handle
  sign-in and 2FA yourself. That is by design, the tools never touch your
  password.
- If a run meets a mid-run "please sign in again" prompt, for an expired
  session say, it cannot answer from here, so it ends. Sign in again and
  press Continue.
- In a checkout, setup-all has to have run once before the panel can run an
  app. The page says so until it has.
