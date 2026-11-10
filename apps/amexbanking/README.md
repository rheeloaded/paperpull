# American Express Banking statement downloader

Downloads your American Express deposit account statements and tax forms as
PDFs from `americanexpress.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

Contributed by [@appchamp](https://github.com/appchamp), whose runs on their
own Business Checking account saved 61 documents, monthly statements back to
2022 and the 1099-INT forms
([#168](https://github.com/rheeloaded/paperpull/pull/168)).

**American Express cards are a different app.** A card is read by the
[`amex`](../amex) app. The two are separate installs with separate sign-in
windows.

**Scope.** American Express National Bank deposit accounts.

- **Business Checking** is confirmed on a real account.
- **Personal Checking and Savings** are read the same way but have not been
  seen yet. If you have one, a Diagnose file attached to the issue tells us
  whether the same list and the same names come back.

## Setup

```bash
./setup.command                  # one-time: venv + Playwright
./login.command                  # opens Edge/Chrome on port 9307, sign in yourself
paperpull amexbanking diagnose   # a safe look, reads the page, downloads nothing
paperpull amexbanking pilot      # download the newest few as a test
paperpull amexbanking all        # download everything available
```

(On Windows, the matching `setup.bat`, `login.bat` and the rest. Copy
`config.example.json` to `config.json` once.)

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), never
the bundled Playwright Chromium, to keep a trusted session without tripping
bot checks.

## How it works

- **You sign in.** The tool attaches over CDP to the window you signed into
  and only reads. It never sees a password and never touches 2FA.
- **The page** is Documents and Statements,
  `https://www.americanexpress.com/en-us/banking/business/checking/accounts/manage/documents`,
  opened by its address, or loaded again when it is open already. Nothing on
  any page is pressed, typed into or chosen.
- **The list** is the one the page asks for itself,
  `ReadBankingAccountDocumentList.v1`, heard as it answers, with the account
  token the page asked it with. Monthly statements are dated the last day of
  their month, and tax forms Dec 31 of their tax year.
- **Each PDF** is asked for by its own id and its own account's token at
  `ReadBankingDocument.v1`, from inside the signed-in page, the way the page
  does. It comes back as base64 and is written only when it is a PDF. A PDF
  that comes back with the bytes of another document saved in the same run
  is not saved, and that document is tried again on the next run.
- **Login** says you are signed in only once the documents list answers. A
  tab that only sits at the page's address says nothing of the session.
- **One account a run**, the one Documents and Statements shows. Its name in
  file names and in the index is read from the page's account switcher once
  the list has answered, or from the page's address (Business Checking,
  Personal Savings and so on) when the switcher cannot be read. To file an
  account under a name of your own, set `account_name` in its config. That
  name goes on everything the config reads, so give a second account a
  config of its own (`login.bat biz2` reads `config.biz2.json`).
- **A list read in part is never called whole.** A list call that did not
  answer, a document whose id, month or year could not be read, a document
  of a kind this app does not know, a list whose own count disagrees with
  what it holds, and lists of more than one account in one page load are
  each a part of the list missing. What was read is downloaded, a failure
  file is written, and the run stops at its end rather than finish. Resume
  reads no list, carries on with what was read, and then stops the same way.
  Pilot or Run All reads the list again.
- **A list that answers with no documents** is what a new account shows, and
  a list that did not load can look the same, so it is not noted as read
  whole, and the run does not stop for it.
- **Signed out.** A list or a PDF that American Express answers with a 401,
  a 403 or a redirect stops the run once, with nothing recorded against the
  document it was on. Sign in again and press Resume.
- **A document is done by its own record.** A PDF already in the folder with
  the same date is never taken for a document, since it may be another
  account's statement of that month.
