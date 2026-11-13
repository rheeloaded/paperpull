# Verizon Mobile bill downloader

The wireless side of My Verizon. Fios and Home Internet bills have their own
app, [apps/verizon](../verizon), which does work.

**Confirmed on a real account** (24 bills, 2026-10-29, [issue #31](https://github.com/rheeloaded/paperpull/issues/31)).
It reads Bill & payment history's own bill list, which holds every cycle My
Verizon keeps, and asks each bill's PDF from inside the signed-in page, the
way the page's own "Review bill PDF" does. Nothing is clicked. See the notes
at the top of `verizonmobile_site.py`.

Downloads your Verizon wireless monthly **bills** as PDFs from My Verizon. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Use it from the panel

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page. The first time you open
   PaperPull it shows its terms and asks which folder your documents go in,
   then shows the same list by itself. Click **Verizon Mobile**, then
   **Continue**, then **Set up**. Back on Accounts, click **Verizon Mobile**
   to open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Unlike the one on the provider's page, it starts no download once
   you are signed in. Your own Edge or Chrome opens with a separate profile.
   Sign in to verizon.com yourself, answer any code it sends, and leave the
   window open. The sign-in says Success only once Bill & payment history
   has listed your bills. Then click **Close** to leave Get help.
4. Click **Try the newest few first**. It lists your bills and saves the
   newest five to `Statements\`. Look at them before you click **Get new
   documents**.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to
[issue #31](https://github.com/rheeloaded/paperpull/issues/31). It is
described in full on the
[Testing a provider](../../docs/testing-a-provider.md#if-a-run-fails-send-the-file-it-wrote)
page. A support report, **Make the report** under **More** and then **Get
help**, writes `Diagnostics\diagnose-billing.json`, a survey of Bill &
payment history that downloads nothing, presses nothing, follows no link,
takes no screenshot, and writes any word that is not on PaperPull's fixed
list as its shape.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9255, sign in yourself
paperpull verizonmobile pilot               REM the newest five bills
paperpull verizonmobile all                 REM every bill My Verizon keeps
```

## How it works

Nothing is ever clicked. The app opens Bill & payment history,
`/digital/nsa/secure/ui/bill/history/`, by its address, in your verizon.com
tab or, with none open, in a tab of its own. A tab of another site is never
used.

- **Real Edge or Chrome.** verizon.com runs bot protection that walls the
  Playwright build of Chromium, which the Fios app proved, so `login.bat`
  launches the browser already on the machine with a separate profile.
- **The list.** The page asks
  `GET /digital/nsa/secure/gw/bill/billpaymenthistory/bill_history` with a
  `channelId` header of its own. The app takes that answer as the page gets
  it. It holds every billing cycle My Verizon keeps, the ones the page
  shows only after Show more among them, each with the day its cycle ended.
- **Whole or stopped.** A history that never comes, answers with an error,
  names no account number, lists no bill, or holds a cycle whose end date
  is not a calendar date or two cycles of one end date stops the run, and
  is never taken for the whole list. What was read before it stopped is
  kept, and the failure file says the list stopped partway.
- **Identity.** A bill is known by its account and the day its cycle ended,
  `bill-4321-00001-2026-10-11`, the last four digits of the account number
  with the suffix after its hyphen, then the day.
- **The PDF.** Each bill is the page's own Review bill PDF address,
  `GET .../bill_pdfdoc?startMonthDate=<end date>&channelId=<the page's channel>`,
  asked from inside the page with the session's cookies and kept only when
  it is a PDF. The app asks for that address on www.verizon.com alone, with
  exactly those two parameters, each of its own shape.
- **One account at a time.** That address names no account, so it gives
  the bill of whichever account My Verizon shows. The history is read again
  for each bill, right before its PDF is asked for, and the bill is asked
  for only when the history shows the account it was listed under. A run
  takes the bills of the account shown first, so a bill of another account
  that was refused or interrupted waits for a run with its own account
  shown and never holds them back. Once only other accounts' bills are
  left, the run stops and names the account it wants by its last four
  digits. Choose that account in My Verizon and run Resume.
- **Signing out.** A refused bill is followed by one more read of the
  history. A sign-out shows there and stops the run, keeping what it saved.
  Sign in again and run Resume. A history that still reads leaves the
  refusal that one bill's, so the run goes on and the next run tries it
  again.
- **Read-only.** Nothing is pressed. `FORBIDDEN_CONTROL_RE`, which blocks
  anything that pays, enrolls in autopay or paperless, changes a plan, adds
  a line, upgrades or trades in a device, suspends service, moves a number,
  or edits the account, is kept so Diagnose can say what it would make of
  each control it sees.

## Scope

- Whatever bills My Verizon lists in Bill & payment history. It keeps about
  24 months of bills online, so run it every month or two.
- Wireless only. A Fios or Home Internet account belongs to
  [apps/verizon](../verizon). An account that has both signs in once and
  runs both apps.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull verizonmobile add-account NAME`).

## Not yet seen

- More than one account on one sign-in. Only the account Bill & payment
  history shows is read. Take one account's bills, then choose the next in
  My Verizon and run Discover and Run All again.
- A history with no bills. It stops the list, since an empty answer cannot
  be told from one cut short.
- Two accounts whose numbers end in the same four digits and suffix. Their
  bills of one day share a key, about 1 in 10,000 for two accounts.

Your account number and the name on the account are kept out of every log
and diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The browser test starts PaperPull's bundled Chromium on
made-up host names, so nothing reaches Verizon.
