# Golden 1 document downloader

**Not yet tested against a real account.** This app was built without
a Golden 1 checking, savings, credit card or loan account, so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
golden1.com is marked in `golden1_site.py`. What it needs is a survey from a
signed-in account, which the Diagnose button produces and which contains
no personal data. The conversation is
[issue #35](https://github.com/rheeloaded/paperpull/issues/35).

Downloads your Golden 1 **statements and tax forms** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Golden 1**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   Golden 1 folder. It downloads nothing, clicks nothing but a documents
   link, takes no screenshot, and masks any run of six or more digits.
5. Open that file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
6. Attach the file to [issue #35](https://github.com/rheeloaded/paperpull/issues/35)
   with a sentence about how you choose which account's statements to see (a dropdown, tabs, a list), and whether tax forms sit with them.
7. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Tax Documents\`, then attach a fresh Diagnose file.

Two or three rounds usually gets a provider working.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9258, sign in yourself
paperpull golden1 diagnose         REM the survey, for the maintainer
paperpull golden1 pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** A credit union's sign-in is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **eStatements.** Discovery tries the statements and documents routes on login.golden1.com in turn and takes the first that is not a sign-in page and looks like a statements list. Every control whose name says it fetches a statement or a tax form ("View", "Download", "Statement PDF", "1099-INT") is read, and the date comes from the control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Tax Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that transfers, pays, sends money by Zelle, wires, deposits, applies, opens or closes an account, locks a card, changes a limit or an address, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the eStatements area lists, statements and tax forms.
- Golden 1 shows statements one account at a time behind an account picker, most likely. The first survey shows what that picker looks like, and the second round drives it, so a first Pilot may only see one account.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull golden1 add-account NAME`).
