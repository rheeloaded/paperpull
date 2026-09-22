# Testing a provider

**You do not need to be a programmer to read this page.** You need an account
with a company PaperPull does not support yet, or one it supports badly, and
about twenty minutes. Nothing here involves writing code or installing
anything but PaperPull itself.

If that is you, you are the most useful person in this project. Nobody can
write a downloader for a bank they do not bank with, because the pages behind
a sign-in cannot be seen from outside. Every provider in PaperPull exists
because somebody with an account did what this page describes.

**Contents**

1. [Why this works](#why-this-works)
2. [What you need](#what-you-need)
3. [Install PaperPull](#install-paperpull)
4. [Add the provider](#add-the-provider)
5. [Sign in](#sign-in)
6. [Record one trip to a document](#record-one-trip-to-a-document)
7. [Read the file before you send it](#read-the-file-before-you-send-it)
8. [Send it](#send-it)
9. [What happens next](#what-happens-next)
10. [What Record captures, exactly](#what-record-captures-exactly)
11. [When something goes wrong](#when-something-goes-wrong)

---

## Why this works

A downloader has to know things nobody can guess. Whether last year's bills
are on the same page as this month's or behind a link. What the download
button is called. Whether the site opens a PDF in a new tab or sends a file
straight down. Whether picking a year reloads the page or quietly fetches the
list in the background.

For a long time the only way to find that out was a survey. The app read the
page, wrote down everything it could see, and somebody guessed from that.
AT&T took **nine rounds** of guessing that way. Each round was a day of
waiting on both sides.

**Record removes the guessing.** You click your way to a document once, the
way you always do, and the app writes down the path you took. The maintainer
reads the path and writes the app to take the same one. Usually that is one
round.

---

## What you need

- **An account** with the provider, with at least one statement, bill or
  receipt in it. An account you opened yesterday has nothing to download and
  nothing to record.
- **Windows 10 or 11, or a Mac with Apple silicon.** Both installers are on
  the releases page.
- **Edge or Chrome.** Whichever you already have. PaperPull opens it with a
  separate profile so your normal browsing is untouched.
- **Twenty minutes.** Ten of it is the install.

You do **not** need a GitHub account to install and run this. You need one to
send the file back, and making one takes two minutes. If you would rather not,
say so on the issue and the maintainer will find another way.

---

## Install PaperPull

Download the installer for your machine from the
[latest release](https://github.com/rheeloaded/paperpull/releases/latest).

**Windows.** Run the `-setup.exe` file. Windows will show a blue box saying
**Windows protected your PC**, because the installer is not signed by a paid
certificate. Click **More info**, then **Run anyway**. If you would rather
not, that is a reasonable position and you can stop here.

**Mac.** Open the `.dmg` and drag PaperPull to Applications. The Mac build
**is** signed and notarized by Apple, so it opens without a warning.

Launch PaperPull. A control panel opens in your browser. Everything from here
happens in that panel.

---

## Add the provider

1. Click **add a provider**.
2. Tick the one you are testing. If it is not in the list, it does not exist
   yet, so
   [open an issue](https://github.com/rheeloaded/paperpull/issues/new/choose)
   asking for it and somebody will build the shell for you to test.
3. Pick it in the **App** list at the top.

PaperPull makes a folder for it, downloads the browser pieces it needs, and
tells you when it is ready. The first provider takes a few minutes. Every one
after that takes seconds.

---

## Sign in

Click **Login**. Your Edge or Chrome opens on the provider's site, in a
profile of its own.

Sign in the way you normally would. Type your password yourself, answer the
text message or the authenticator code yourself, tick **remember this device**
if it offers. PaperPull is not watching this part. It cannot be, and the next
section explains why that is enforced rather than promised.

Then navigate to wherever your documents live and **leave that window open**.
Do not close it and do not go back to the control panel yet.

---

## Record one trip to a document

1. In the control panel, click **more** under the buttons.
2. Click **Record**.
3. The panel prints a short notice saying what is being recorded. Read it.
4. Go back to the browser window and **click your way to one document**, the
   way you always do. Pick the year, open the bill history, click the
   download link, whatever your provider asks for. Do it once, at your normal
   pace. You can download the document if that is the last step. The file is
   yours and it stays on your machine.
5. Come back to the panel and click **Stop recording**.

That is the whole thing. It writes one file, `recording.json`, in the
provider's `Diagnostics` folder. The panel prints where.

**Record one path, not five.** A recording of you clicking around exploring is
harder to read than one clean trip. If you take a wrong turn, stop, and record
it again.

**If you prefer a terminal**, the same thing is `paperpull <provider> record`
and it ends when you press Enter.

---

## Read the file before you send it

**Open `recording.json` in Notepad or TextEdit and read it through.** This is
the step people skip and it is the one that matters, because the file is going
onto a public issue where anyone can read it.

The app has already removed what it can. Email addresses, dollar amounts,
anything with six or more digits in a row, the account holder's name where it
knows it, and the values after the `?` in an address, keeping only the names of
the settings so a maintainer can see there was a year filter without seeing
which year. What is left should be page headings, the names of buttons and
links, and the shapes of the data the site loaded, with no values in them.

**The app points at what to check.** When the recording ends it prints a short
list of things worth a look, quoting each one so you can find it. That list is
not a verdict and it is not complete, but it puts you in the right place. The
first two below are what it looks for, because they are the two things the
masking cannot do on your behalf. The third one is you.

- **A four or five digit number.** The masking starts at six digits so that a
  year stays readable. If you see a short number that is part of an account
  number, replace it with `xxxx`.
- **A name.** If the app was not told the account holder's name, a name
  sitting on a profile button will still be there. Replace it.
- **Anything else you would not want public.** It is your file. Delete any
  line you do not like the look of. A recording with three lines missing is
  still useful. Nobody will ask you why.

Save it when you are done.

---

## Send it

Go to the issue for your provider. Every untested provider has one, and the
[provider table](https://github.com/rheeloaded/paperpull#paperpull) in the
README links to it from that provider's row. If there is no issue,
[open one](https://github.com/rheeloaded/paperpull/issues/new/choose).

Drag `recording.json` into the comment box. GitHub attaches it. Add a sentence
or two in your own words about anything the recording cannot show. Something
like this is plenty.

> Older bills are behind the year dropdown, and it only goes back three years.
> The PDF opened in a new tab rather than downloading.

Post it.

---

## What happens next

The maintainer reads the recording, writes the site layer, and posts a new
build, usually within a few days. You update PaperPull, click **Pilot**, and
say whether the documents landed in the provider's folder.

If they did, you get a line in the README under Thanks, with your GitHub
username, and the provider stops being marked untested. If they did not,
record it again on the new build and say what happened instead. Two rounds is
normal. Nine was the old way.

---

## What Record captures, exactly

This is the whole list. It is worth reading once even if you trust the
project, because the point of writing it down is that you can check it against
[the code](https://github.com/rheeloaded/paperpull/blob/main/core/paperpull_core/recorder.py).

**It records**

- Each control you click, named the way you read it on the page. "The link
  called Bill and payment history."
- Which option you picked in a dropdown.
- Whether a checkbox ended up ticked.
- That the page moved, and where to, with everything after the `?` removed.
- That a new tab opened, and whether it was still on the provider's site.
- That a file downloaded, and what it was called.
- The addresses of the provider's own data requests and the **shape** of what
  came back, meaning the names of the fields and whether each one held a
  number or some text. Never the contents.

**It does not record what you type.** Not the text, not a password, not a
one-time code, not a search term. This is not a filter applied afterwards.
There is no keystroke listener in the recorder at all, so there is nothing for
a password to be captured by. A field you typed in is recorded as having been
typed in, and its value is written as the word `[REDACTED]`, which is a fixed
word in the source and never your text.

**It does not read cookies, headers or browser storage.** The recorder never
calls anything that reads them, so a recording cannot carry your session even
by accident. There is an automated test that fails the build if that code is
ever added.

**It will not start before you are signed in.** Record checks that the page is
on the provider's own site, that the app does not think you are signed out,
and that there is no password box on the page. If any of those fail it refuses
and says why. A recorder you could switch on at a sign-in screen would be a
keylogger with good intentions, so this one cannot be.

**Nothing leaves your machine.** The file is written to your own disk. You
read it, you edit it, and you decide whether to send it.

---

## When something goes wrong

**Record refuses and says you are not signed in.** You are on the wrong page,
or the session expired while you were reading this. Click **Login** again,
sign in, get to the documents page, and try again.

**Record refuses and says there is a password field on the page.** That is the
check working. Get past the sign-in first.

**Nothing was recorded, the file has no steps.** The page was replaced between
you pressing Record and your first click, which happens on sites that reload
themselves a moment after loading. Wait for the page to settle, then press
Record and click straight away.

**Your clicks are recorded but nothing happens on the site.** That is fine.
Record watches, it does not drive. If the site is broken, it is broken for
reasons unrelated to PaperPull.

**The provider's site logs you out constantly.** Record what you can and say
so on the issue. Short sessions are a real property of the site and the app
will have to deal with it, so knowing is useful.

**You would rather not run an unsigned installer.** Say so on the issue. A
[Diagnose](../CONTRIBUTING.md#fixing-a-provider-that-broke) file from an
existing install is less complete but still helps, and the signing situation
is explained in [docs/code-signing.md](code-signing.md).

**Anything else.**
[Open an issue](https://github.com/rheeloaded/paperpull/issues/new/choose) and
say what you did and what happened. A confused report is more useful than no
report.
