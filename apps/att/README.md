# AT&T bill downloader

**Working on the tester's account, still being finished.** This app was
built without an AT&T account and repaired across eight rounds from the
surveys and traces one tester sent. Round eight's pilot saved his bills.
What is still open is the full history run and a household with more than
one account (he holds wireless and fiber, and only the account in focus is
read so far). The conversation is
[issue #26](https://github.com/rheeloaded/paperpull/issues/26), and the
steps below are still how a round works.

Downloads your AT&T monthly **bills** as PDFs from myAT&T. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **AT&T**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to att.com yourself, answer any code it sends, and leave the
   window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the billing page and writes
   `Diagnostics\diagnose-billing.json` in the AT&T folder. It downloads
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
7. Attach both files to [issue #26](https://github.com/rheeloaded/paperpull/issues/26)
   with a sentence about what the billing page looks like to you.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\`, then attach a fresh Diagnose file.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9252, sign in yourself
paperpull att diagnose            REM the survey, for the maintainer
paperpull att pilot               REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** att.com runs Akamai bot protection that walls
  the Playwright build of Chromium, as Verizon's does, so `login.bat`
  launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Bill history.** Discovery tries the myAT&T billing history routes in
  turn and takes the first that is not a sign-in page and looks like
  billing. Every control whose name says it fetches a bill ("Download
  bill", "View bill (PDF)") is read, and the bill date comes from the
  control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever att.com does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, enrolls
  in autopay or paperless, changes a plan, adds a line, upgrades or trades
  in a device, suspends service, moves a number, or edits the account. A
  control must also look like a document action before it can be clicked.

## Scope

- Whatever bills myAT&T lists on its history page. AT&T keeps about
  eighteen months of bills online, so run it every month or two.
- Wireless, Fiber and Internet accounts share myAT&T, so one app should
  cover any of them once the site layer is confirmed.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull att add-account NAME`).
