# MILITARY STAR card statement downloader

Downloads your own **MILITARY STAR card statements** from MyECP
(www.myecp.com), the Exchange Credit Program's site, as PDFs, for your
records. Read-only, delete-safe, and part of [PaperPull](../../README.md).

Mapped and run against the maintainer's own card account on 2026-09-25.
Twenty-five statements, April 2023 to September 2026, each checked against
the closing date it prints, and a second run downloaded nothing.

## How it reads the site

After sign-in, MyECP lands on the **Account Summary**. Each card
account's **Statements** tab loads a small page fragment with a dropdown
of statement dates, and the Download button fetches the chosen one as a
PDF. This app asks for that same fragment and those same PDFs from inside
the signed-in page, so the session never leaves the browser, and it
clicks nothing.

The site numbers statements by their position in that dropdown, which
moves every month, so the app knows a statement by its date and looks up
its current position when it downloads. Filenames read like
`2026-09-05 MILITARY STAR Monthly Statement.pdf`.

**What it does not cover.** The site keeps about three and a half years
online and says to contact the Exchange for anything older. Payment
history and rewards activity are tables, not documents.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself and leave the window open. The app never sees your
password. If a run stops with "session has ended", sign in again in the
open window and resume.

## Safety

This is a credit card account. The site can take payments, add
authorized users, redeem points and apply for credit. This app activates
no control at all. It reads the statements fragment and the PDFs it names
and nothing else, every address on `myecp.com`, and an expired session
stops the run rather than reporting an empty success. The click guard
every other app uses is kept and tested here too.

## Commands

```
paperpull myecp setup
paperpull myecp login        sign in yourself, leave the window open
paperpull myecp discover     list what the site has, download nothing
paperpull myecp pilot        the newest five
paperpull myecp all          everything, delete-safe on a rerun
paperpull myecp verify       re-check every saved PDF
paperpull myecp diagnose     survey the page and the list, for when it changes
```

## Tests

```
python -m pytest tests -q
```
