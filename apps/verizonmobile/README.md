# Verizon Mobile bill downloader

The wireless side of My Verizon. Fios and Home Internet bills have their own
app, [apps/verizon](../verizon), which does work.

**Not yet tested against a real account.** This app was built without a
Verizon Mobile account, so that someone who holds one can test it without writing
code. It runs, its guards are tested, and every guess about verizon.com is
marked in `verizonmobile_site.py`. What it needs is a survey from a signed-in
account, which the Diagnose button produces and which contains no personal
data. If you have a Verizon wireless account, the steps are below, and the conversation is
[issue #31](https://github.com/rheeloaded/paperpull/issues/31).

Downloads your Verizon wireless monthly **bills** as PDFs from My Verizon. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Verizon Mobile**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to verizon.com yourself, answer any code it sends, and leave the
   window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the billing page and writes
   `Diagnostics\diagnose-billing.json` in the Verizon Mobile folder. It downloads
   nothing, clicks nothing but a billing link, takes no screenshot, and
   masks any run of six or more digits.
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
7. Attach both files to [issue #31](https://github.com/rheeloaded/paperpull/issues/31)
   with a sentence about what the billing page looks like to you.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\`, then attach a fresh Diagnose file.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9255, sign in yourself
paperpull verizonmobile diagnose            REM the survey, for the maintainer
paperpull verizonmobile pilot               REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** verizon.com runs bot protection that walls the
  Playwright build of Chromium, which the Fios app proved, so `login.bat`
  launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Bill history.** Discovery tries the My Verizon wireless bill routes
  under `/digital/nsa/secure/ui/` in turn, then the Download Your Bill page
  the Fios app drives, and takes the first that is not a sign-in page and looks like
  billing. Every control whose name says it fetches a bill ("Download
  bill", "View bill (PDF)") is read, and the bill date comes from the
  control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever verizon.com does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, enrolls
  in autopay or paperless, changes a plan, adds a line, upgrades or trades
  in a device, suspends service, moves a number, or edits the account. A
  control must also look like a document action before it can be clicked.

## Scope

- Whatever bills My Verizon lists on its history page. Verizon keeps about
  eighteen months of bills online, so run it every month or two.
- Wireless only. A Fios or Home Internet account belongs to
  [apps/verizon](../verizon). An account that has both signs in once and
  runs both apps.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull verizonmobile add-account NAME`).
