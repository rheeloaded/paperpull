# E*TRADE document downloader

**Not yet tested against a real account.** This app was built without
an E*TRADE brokerage or retirement account, so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
etrade.com is marked in `etrade_site.py`. What it needs is a survey from a
signed-in account, which the Diagnose button produces and which contains
no personal data. The conversation is
[issue #36](https://github.com/rheeloaded/paperpull/issues/36).

Downloads your E*TRADE **statements, trade confirmations and tax forms** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **E*TRADE**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   E*TRADE folder. It downloads nothing, clicks nothing but a documents
   link, takes no screenshot, and masks any run of six or more digits.
5. Click **Record**, in the same **more** menu. Go back to the browser window
   and click your way to one document the way you normally would, then come
   back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough, written
   for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
7. Attach both files to [issue #36](https://github.com/rheeloaded/paperpull/issues/36)
   with a sentence about how statements, confirmations and tax forms are separated (tabs, a dropdown, one list), and how you choose the account.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Tax Documents\`, then attach a fresh Diagnose file.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to the issue the same
way. It is what keeps the rounds after the first one short, and it is
described in full on the
[Testing a provider](../../docs/testing-a-provider.md#if-a-run-fails-send-the-file-it-wrote)
page.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9260, sign in yourself
paperpull etrade diagnose         REM the survey, for the maintainer
paperpull etrade pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Etrade.com runs bot protection that is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents.** Discovery tries the documents and statements routes on us.etrade.com in turn and takes the first that is not a sign-in page and looks like a documents list. Every control whose name says it fetches a statement, a confirmation or a tax form ("View", "Download", "Statement PDF", "1099") is read, and the date comes from the control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Tax Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that trades, buys, sells, places or cancels an order, transfers, wires, deposits, withdraws, takes a distribution, links a bank, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the documents area lists. Statements, trade confirmations and tax forms, filed to `Statements\` (confirmations included, named Trade Confirmation) and `Tax Documents\`.
- Trade confirmations arrive per trade and can run to hundreds. If you only want statements, drop nothing yet, the first survey shows how they are separated and the second round adds a switch.
- E*TRADE shows documents one account at a time behind an account picker, most likely. The first survey shows what that picker looks like, and the second round drives it.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull etrade add-account NAME`).
