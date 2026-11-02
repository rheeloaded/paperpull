# Bank of America statement downloader

Downloads your own **Bank of America statements** as PDFs, checking,
savings and credit card accounts alike, for your records. Read-only,
delete-safe, and part of [PaperPull](../../README.md).

**UNTESTED.** Built on 2026-10-25 from two recordings a tester made on
[issue #121](https://github.com/rheeloaded/paperpull/issues/121), one trip
to a checking statement and one to a credit card statement. Its first run
on an account, on 2026-10-26, listed every statement and saved none, since
the page drew no Download PDF link until its Statements heading was opened,
which the app now does. Its second, on 2026-10-27, met Download PDF links
that open their PDF by a script of the page's own, with no address to
read, so the app now presses one such link to learn how the page asks for
a PDF. If you bank with Bank of America, a Pilot run tells whether it
works, see below. Tax forms are not covered yet.

## How it reads the site

Statements & Documents fills its list from a call of its own, one account
and one year at a time, and draws a Download PDF link for each statement
under its Statements heading. The app reloads that page, keeps the list
call the page makes, and asks every account's statements the same way from
inside the page, year by year, at a person's pace, and reloads the page
again only when what it heard is five minutes old, in a long run. A reload
leaves the Statements heading shut, with no link drawn under it, so before
it downloads, the app opens that heading. It learns the form of the page's
own Download PDF links and asks for each statement at its own address in
that form. When the links have no address, since the page opens each PDF
by a script of its own, the app presses one of them, once a run, and
learns the call the page makes for that PDF instead. It keeps nothing the
press brought, asks that call once more for the same statement to be sure
it answers with a PDF, and then asks each statement with its own call.

A statement is filed only when its text names its own day and account
better than any statement it could be taken for, the other accounts'
statements of that day and its own account's either side of it. Anything
else goes to `Manual Review`, a file the bank names for another day than
its statement among them, and is never filed. Anything on the page that does not fit what the recordings
showed stops the run, with a failure file that says what, rather than a
guess.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest),
   or update your checkout, and open the control panel.
2. Click **add a provider** and tick **Bank of America**. Pick it in the
   App list.
3. Click **Login**. Your own Edge or Chrome opens on bankofamerica.com,
   with a separate profile. Sign in yourself and answer any code it sends.
4. In that window, open **Statements & Documents**, the way you normally
   would, and leave the window there.
5. Click **Pilot**. It lists every account's statements and downloads the
   newest five into the `Statements` folder. To try a single statement
   first, run it from a terminal with `--max-docs 1`, for example
   `python paperpull.py bofa pilot --max-docs 1` in a checkout.
6. Look at what landed. A statement in `Statements` was checked against
   its day and account. One in `Manual Review` was not filed, and the run
   says why.
7. Say on [issue #121](https://github.com/rheeloaded/paperpull/issues/121)
   whether the statements are the right ones, and paste any line that
   starts with `Waited for`.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts
and states, with no text from your account in it. Attach it to the issue
the same way. **Diagnose**, under **more**, writes one too while the window
is on Statements & Documents, saying what the list answered as counts and
names only.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, answer your own code, and leave the window open. The app
never sees your password. Login says you are signed in only when the
statements list answered, so it asks you to open Statements & Documents
first. With other Bank of America tabs open, it works in the one on
Statements & Documents, and with more than one there it stops and asks you
to close the others.

## Safety

Bank of America moves money, through transfers, Zelle and bill pay. This
app presses two controls of Statements & Documents, each only with nothing
drawn over it and only when a statement is to be downloaded. One is the
Statements heading, when the page shows it shut, and only a button whose
whole name is Statements. The other is one statement's Download PDF link,
once a run, when no link shows an address. It has to be a link, not a
button, whose words beside the bank's own names for your statements and
accounts start with Download PDF for and hold nothing the app's blocklists
refuse, read again right before the press. The link is focused first, so
any overlay the page shows when it receives focus is brought up. A
download that press starts is cancelled and a tab it opens is closed.
Login and Discover press nothing, and Diagnose never presses a link. It reloads Statements &
Documents to hear its list, at the start and every five minutes of a long
run, and asks for lists and PDFs from inside the signed-in page the way the
page itself does, every address on `bankofamerica.com`. Login opens the home page in a tab of its own only
when no tab of yours is on the site. An expired session stops the run
rather than reporting an empty success.

## Commands

```
paperpull bofa setup
paperpull bofa login        sign in, open Statements & Documents, leave it open
paperpull bofa discover     list every account's statements, download nothing
paperpull bofa pilot        the newest five (add --max-docs 1 for one)
paperpull bofa all          everything, delete-safe on a rerun
paperpull bofa resume       carry on after a run that stopped
paperpull bofa verify       re-check every saved PDF
paperpull bofa diagnose     survey the page and its statements list
paperpull bofa record       record one trip to a statement, press Enter to stop
```

## Tests

```
python -m pytest tests -q
```
