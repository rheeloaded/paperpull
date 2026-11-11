# MBNA statement downloader

Will download your own **MBNA Canada credit card statements** as PDFs, for
your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

**NOT BUILT YET.** This is a first shell, made for
[issue #205](https://github.com/rheeloaded/paperpull/issues/205). It opens
MBNA's sign-in page in a browser profile of its own so you can sign in, and
it lets Record and Diagnose watch the page you leave open. That is all it
does. Discover, Pilot and Run All say it is not built yet and stop, Resume
says nothing has been listed yet, and nothing is listed or downloaded.
Which page lists your statements, how two cards under one sign-in are told
apart, and how a statement's PDF arrives cannot be seen without an account,
so the real app is built from a recording of one trip to a statement, made
by someone who holds the card.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open it. On a Mac it opens in a window of its own.
2. On Accounts, click **Add a provider** and tick **MBNA**. Then click its
   row to open it.
3. Click **Open sign-in window**. Your own Edge or Chrome opens on MBNA's
   sign-in page, with a separate profile. Sign in yourself, answer any
   code it sends, and leave the window open. Use the site in English while
   you record. Record keeps only the words on PaperPull's list, and the
   list has no French yet.
4. In that window, open the page with your statements on it, the way you
   normally would.
5. In PaperPull, open **More**, then **Get help**, and press **Record
   steps**. Go back to the browser and click your way to one statement's
   PDF, at your normal pace, then come back and press **Stop recording**.
   It writes `Diagnostics/recording.json`, records nothing you type and
   reads no cookies. The whole walkthrough is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open `recording.json` in TextEdit or Notepad and read it through. If
   anything in it looks personal, delete that line.
7. Attach it to [issue #205](https://github.com/rheeloaded/paperpull/issues/205),
   with a sentence or two about anything the recording cannot show, such
   as how far back the statements go or whether you hold more than one
   card.

**If a run stops early, send the file it wrote.** Once this app is built,
a run that fails leaves a `failure-*.json` in the `Diagnostics` folder and
prints where it put it. It says which step broke and what the page looked
like at the time, as counts and states, with no text from your account in
it. Attach it to the issue the same way. This first build stops before it
reads anything, so a Discover or Pilot that says it is not built yet
writes none.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. The
window opens the address MBNA's own Login links lead to, which hands over
to MBNA's sign-in page on `authentication.mbna.ca`. You sign in yourself,
answer your own code, and leave the window open. The app never sees your
password. Login says what the window shows, a sign-in page or a check, and
since this first build does not read your card it never says you are
signed in. PaperPull starts no run by itself once you have signed in, since
there is nothing to download yet.

## Safety

An MBNA card takes payments, balance transfers and cash advances, and its
pages can raise a credit limit, start an installment plan, redeem rewards
and add a user. This first build presses nothing on MBNA's pages at all.
Login opens the sign-in page in a tab of its own only when no tab of yours
is on the site, and Diagnose reads the page you left open and follows
nothing. Every address it will act on is under `mbna.ca`.

## Commands

```
paperpull mbna setup
paperpull mbna login        sign in yourself, leave the window open
paperpull mbna record       record one trip to a statement, press Enter to stop
paperpull mbna diagnose     survey the page you left open, download nothing
```

Discover, Pilot and All say this app is not built yet and stop, and Resume
says nothing has been listed yet.

## Tests

```
python -m pytest tests -q
```
