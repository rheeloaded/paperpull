# Contributing to PaperPull

This page assumes you have never used GitHub and never contributed to an
open-source project. It walks through everything, from making an account to
seeing your change merged. If you already know your way around, skip to
[the rules](#the-rules) and [adding a provider](#adding-a-provider).

**Contents**

1. [Ways to help that need no code](#ways-to-help-that-need-no-code)
2. [What you need](#what-you-need)
3. [One-time setup](#one-time-setup)
4. [Run PaperPull from the source](#run-paperpull-from-the-source)
5. [Make a change and send it in](#make-a-change-and-send-it-in)
6. [Adding a provider](#adding-a-provider)
7. [Fixing a provider that broke](#fixing-a-provider-that-broke)
8. [The rules](#the-rules)
9. [What happens after you send it](#what-happens-after-you-send-it)
10. [When something goes wrong](#when-something-goes-wrong)
11. [For maintainers, cutting a release](#for-maintainers-cutting-a-release)

---

## Ways to help that need no code

You do not have to write code to be useful. All of these happen on the
GitHub website with nothing installed.

**A provider stopped working.** Go to
[New issue](https://github.com/rheeloaded/paperpull/issues/new/choose) and
pick **A supported app stopped working**. Say which provider, what you ran,
and what it did. Leave out account numbers, balances and anything with your
name in it. A report that says "Chase, ran Pilot, it found zero statements
where last month it found twelve" is exactly enough.

**You want a provider that does not exist.** Same page, pick **Request a
provider**. Say who the provider is and what documents they offer. Someone
with an account there may build it, and if you have the account yourself,
read on, because you are the person best placed to.

**You tried the installer.** Tell us how it went, good or bad. Open an issue
and say which operating system, what you expected, and what happened. The
installer is new and the only way it gets better is people other than the
author using it.

**The docs are wrong or confusing.** Every page on GitHub has a pencil icon
at the top right when you are signed in. Click it, fix the words, and GitHub
walks you through sending the fix. That is a real contribution and it goes
through the same review as code.

---

## What you need

For code changes, all of the following. Each is free.

- **A GitHub account.** [github.com/signup](https://github.com/signup). Pick
  a username you are happy to have on the internet, since it appears next
  to everything you contribute. Turn on two-factor authentication under
  Settings, Password and authentication. GitHub requires it for
  contributors and it protects the account that will have your changes
  under its name.
- **Git**, the program that moves code between your computer and GitHub.
  Windows, install [Git for Windows](https://git-scm.com/download/win) and
  accept every default. macOS, open Terminal, type `git`, and if it is not
  there macOS offers to install it.
- **Python 3.11 or newer.** Windows, install from
  [python.org/downloads](https://www.python.org/downloads/) and tick **Add
  python.exe to PATH** on the first screen of the installer, the one box
  people miss. macOS, [python.org/downloads](https://www.python.org/downloads/)
  as well, the one Apple ships is too old.
- **A Chromium-based browser.** Chrome, Edge, Brave, Vivaldi or Opera. Edge
  is already on every Windows machine. Safari and Firefox cannot be driven
  this way.
- **An account with the provider** you want to work on. Everything here is
  tested against a real account, your own. There is no other way to know a
  downloader works.

A note on the terminal. Several steps below say "in a terminal". On Windows
that means PowerShell, found by pressing the Windows key and typing
`powershell`. On macOS it is Terminal, in Applications, Utilities. You type a
line, press Enter, and read what comes back. Nothing here needs you to be
comfortable there beyond that.

---

## One-time setup

You do this once. Afterwards every change follows the shorter loop in the
next sections.

### 1. Fork the repository

A fork is your own copy of PaperPull on GitHub, under your username. You
can change it freely, and later you ask for your changes to be pulled into
the main copy. That request is a "pull request", and it is how every
contribution arrives.

Go to [github.com/rheeloaded/paperpull](https://github.com/rheeloaded/paperpull)
and click **Fork** at the top right. Accept the defaults and click **Create
fork**. You land on `github.com/YOUR-USERNAME/paperpull`.

### 2. Clone your fork to your computer

Cloning downloads your fork to a folder on your machine. In a terminal, go to
where you want the folder, then run this with your username in place of
`YOUR-USERNAME`:

```bash
git clone https://github.com/YOUR-USERNAME/paperpull.git
cd paperpull
```

The first line creates a `paperpull` folder holding the whole project. The
second moves your terminal into it. Every command from here on is run from
inside that folder unless it says otherwise.

### 3. Tell Git who you are

Git stamps every change with a name and an email. Use the username you chose
and the private email GitHub gives you, so your real address is not in the
public history. Find the private address under Settings, Emails, it looks
like `12345678+YOUR-USERNAME@users.noreply.github.com`.

```bash
git config user.name "YOUR-USERNAME"
git config user.email "12345678+YOUR-USERNAME@users.noreply.github.com"
```

### 4. Connect your clone to the main copy

Your clone knows about your fork. It should also know about the original,
so you can pick up changes other people make. By convention the original is
called `upstream`.

```bash
git remote add upstream https://github.com/rheeloaded/paperpull.git
```

That is the whole setup. To check it, `git remote -v` should list `origin`
(your fork) and `upstream` (the original), each twice.

---

## Run PaperPull from the source

Before changing anything, make sure the code runs on your machine as it is.
Then when something breaks later you know it was your change.

Each provider app has its own small Python environment. Set one up for the
app you care about, using the folder name under `apps/`. Chase as the
example:

```bash
python paperpull.py chase setup
```

On macOS use `python3` wherever this page says `python`. This creates
`apps/chase/.venv` and installs what the app needs. It takes a minute. Then:

```bash
python paperpull.py chase login
```

A browser window opens. Sign in to the provider yourself, including any
two-factor step, open the statements page, and leave the window open. Back
in the terminal:

```bash
python paperpull.py chase pilot
```

That downloads the five newest documents into the app's folder so you can
look at them. If it works, you have a working development setup and have
also just seen the whole shape of every app. Sign in yourself, the tool
attaches to that browser, reads, downloads, remembers what it got.

`python paperpull.py list` shows every app it can see, and
`python paperpull.py chase diagnose` writes what the app sees on the page to
`apps/chase/Diagnostics`, which is the first thing to look at when a
provider misbehaves.

The control panel, the same thing with buttons, is `gui\run_gui.bat` on
Windows or `gui/run_gui.command` on macOS. It opens in your browser.

**What just landed on your disk, and why it must stay there.** `config.json`,
the `*-browser-profile` folder (your signed-in session), the PDFs, and the
`progress.json` history are all inside `apps/chase/` now. They are listed in
`.gitignore`, so Git will not send them anywhere, and you will check that
yourself before every change goes out. See [the rules](#the-rules).

---

## Make a change and send it in

This is the loop for any change, a one-line fix or a whole provider.

### 1. Start from the latest code

Other people's changes land in the original all the time. Before you start,
pull them into your copy so you are not working on stale code.

```bash
git checkout main
git pull upstream main
git push origin main
```

### 2. Make a branch

A branch is a named line of work. Every change you send in lives on its own
branch, so it can be reviewed and merged on its own. Name it for what it
does.

```bash
git checkout -b fix-chase-year-picker
```

### 3. Make the change

Edit files with any editor. [VS Code](https://code.visualstudio.com/) is
free and knows Python and Git. Notepad works too.

Which file to edit depends on what you are doing. For a provider that
changed its site, it is almost always that app's `*_site.py`, which holds
every selector, URL and page behaviour for that provider and nothing else.
For a new provider, see [adding a provider](#adding-a-provider). For docs,
the `.md` file you are reading.

### 4. Run the tests

Every app has tests in its `tests/` folder, and there are repo-wide tests
that every app must pass. Run both. From inside the app's folder, using the
environment you set up:

```bash
cd apps/chase
.venv\Scripts\python -m pytest tests
cd ../..
```

On macOS the middle line is `.venv/bin/python -m pytest tests`. Then the
repo-wide ones, from the repository folder, using any app's environment:

```bash
apps\chase\.venv\Scripts\python -m pytest core\tests
```

Green means every line ends in `passed`. A failure prints the test's name
and what it expected. The repo-wide tests are the ones that check every app
is read-only, refuses controls that pay or change settings, and will not
click whatever a loose selector happens to find. If one of those fails on
your change, it is telling you something the review would have said.

### 5. Check what you are about to send

This is the step that matters most, and it takes ten seconds.

```bash
git status
```

It lists every file that changed. Read the list. It should hold only source
files, the `.py`, `.md`, `.json` and `.bat` files you meant to touch. If you
see `config.json`, anything ending in `-browser-profile`, a `.pdf`, a `.csv`,
`progress.json`, `discovery.json`, or a `Logs` or `Diagnostics` folder,
stop. Those are yours and must never go out. They are gitignored, so seeing
one means something unusual happened. Ask on the issue rather than guessing.

Then look at the actual changes:

```bash
git diff
```

Read through it once for anything personal. An account number in a test
fixture, your name in a comment, a path with your username in it. The repo
has had exactly this happen and it is far easier to catch here than to
scrub out of history afterwards.

### 6. Commit

A commit is a saved set of changes with a message. Stage the files you
changed, then commit with a message that says what and why in a sentence.

```bash
git add apps/chase/chase_site.py apps/chase/tests/test_doc_types.py
git commit -m "chase, the year picker moved inside the accordion, follow it there"
```

Name the files rather than using `git add .`, so you cannot stage something
you did not mean to. A commit message written as a sentence about the
change is the style here. Look at `git log` for examples.

### 7. Push the branch to your fork

```bash
git push -u origin fix-chase-year-picker
```

The first push of a branch needs `-u origin BRANCH`. After that, `git push`
on its own is enough.

### 8. Open the pull request

Go to your fork on GitHub. A yellow banner says your branch had recent
pushes, with a **Compare & pull request** button. Click it. If the banner is
gone, the Pull requests tab has a **New pull request** button, and you pick
your branch on the right-hand side.

The page shows a template. Fill it in, all of it. The checklist is not
decoration. Each box is something the review will check, and ticking it
means you did. Give the pull request a title that says what it does, and in
the description say what was wrong, what you changed, and how you tested
it, including that you ran it against your own account.

Click **Create pull request**. That is it. Your change is now visible to the
maintainer and to anyone else, with a page of its own where the
conversation happens.

### 9. Respond to review

The maintainer reads the change and either merges it or asks for something.
Questions and requests appear as comments on the pull request page, and you
get an email. To change something in response, edit the files, run the
tests, and commit and push again on the same branch. The pull request picks
the new commits up by itself. There is no need to open a new one.

It is normal for a first contribution to go a round or two. Every provider
so far has needed at least one small fix on the way in, usually the same
one, and none of that reflects on the contributor.

### 10. After it merges

Your branch's work is now in the original. Bring your copy up to date and
delete the branch, which has done its job.

```bash
git checkout main
git pull upstream main
git push origin main
git branch -d fix-chase-year-picker
```

---

## Adding a provider

This is the most valuable thing anyone can contribute, because no one
person has accounts everywhere. The full guide is
[docs/adding-a-provider.md](docs/adding-a-provider.md). It covers the
architecture, how to explore a site, the download mechanisms seen so far,
and the mistakes that cost time. Read it before starting. What follows is
the shape, so you know what you are signing up for.

Budget a few evenings. Most of the time goes into working out how one
particular site lays out its documents and hands over a PDF, and that
cannot be rushed.

1. **Claim it.** Open
   [I'll build a provider](https://github.com/rheeloaded/paperpull/issues/new/choose)
   so two people do not build the same thing. Check
   [PROVIDERS.md](PROVIDERS.md) first for what exists and what is claimed.
2. **Copy the closest app.** Under `apps/`, copy the folder of the app most
   like your provider to a new folder named with a short slug (`chase`,
   `pge`, `usbank` are examples). Rename the two entry files to
   `<slug>_docs.py` and `<slug>_site.py` and replace the old provider's name
   and slug throughout. The guide says which app to copy for which kind of
   provider.
3. **Pick a port.** Every app opens its sign-in browser on its own port so
   several can be signed in at once. Look at `apps/*/config.example.json`
   for the numbers in use and take the next one. At the time of writing
   9222 through 9247 are taken, so the next is 9248. Put it in your
   `config.example.json`.
4. **Sign in and explore.** `python paperpull.py <slug> login`, sign in, open
   the documents page, then `python paperpull.py <slug> diagnose` to see
   what the app can find. The guide explains how to work out where the
   document list is and how a PDF is delivered, which is the whole problem.
5. **Write `<slug>_site.py`.** Navigation to the documents page, collecting
   the list, downloading one. This is the only file with real work in it.
   The rest of the app is shared and does not change.
6. **Tune the guard.** `FORBIDDEN_CONTROL_RE` in your site file is the list
   of words that must never be clicked on this provider. Add the ones that
   pay, transfer or change settings on this particular site. Every click
   goes through it, and a repo-wide test checks that.
7. **Test it against your account.** `pilot` downloads a few. Open them, make
   sure they are the right documents. Run `pilot` again and confirm it
   skips what it already has. Then `all`, and check the count against what
   the site shows.
8. **Write tests.** Copy the pattern in the app you cloned. Every fixture
   must be made up, no real names, numbers or dates from your own
   statements.
9. **Add a row** to [PROVIDERS.md](PROVIDERS.md) and to the table in
   [README.md](README.md).
10. **Send it** using the loop above. The pull request template has a
    section for a new provider. Fill in the reviewer notes, since you know
    things about this site nobody else does.

When it merges it is marked in the provider table as ported with a fresh
live pilot pending, meaning reviewed and tested by you but not yet by the
maintainer, who has no account there. That is the honest state and it
stays until someone else confirms it.

---

## Fixing a provider that broke

Sites change. When a provider's app stops finding documents, the fix is
almost always in that app's `*_site.py`, and the process is the loop above
with one extra step at the start. Run `python paperpull.py <slug> diagnose`
and read what it wrote to the app's `Diagnostics` folder. It shows what the
app found on the page, which controls it saw, and which the guard would
allow, so you can see where the site moved. Then fix the selector or the
navigation, run the tests, run `pilot` against your account, and send it.

If you cannot fix it but can see what changed, that alone is worth an issue.
Say what `diagnose` reported. Someone else can take it from there.

---

## The rules

Three of them. A pull request that breaks one cannot be merged, no matter
how good the rest is.

**Read-only, always.** An app may navigate, read a document list, and
download PDFs the provider already generated. It must never click anything
that pays, transfers, redeems, enrolls, disputes, submits a form, confirms a
dialog or changes a setting. Every click on a provider's page goes through
that app's guard, a blocklist of words that must never be clicked and an
allowlist of words a document action has. A control must pass both. There
is no code anywhere that submits a form, and the review will refuse code
that adds some.

**Never handle credentials.** The user signs in themselves in a real browser
window. The app attaches to that already-signed-in session. Code never sees
a password, never types into a login field, and never touches a two-factor
prompt.

**Never send private data.** No real `config.json`, no browser profile, no
PDFs, logs, CSVs or history files. No real names, account numbers, balances
or personal file paths in code, comments, tests or fixtures. `git status`
and `git diff` before every commit, and read them. This repository has had
private data reach the public history once, from a test fixture, and it
took a history rewrite to remove. See [SECURITY.md](SECURITY.md).

Two smaller things that make review faster. Keep a pull request to one
change, so a fix and a new provider are two pull requests, not one. And
keep the tests green, both the app's own and the repo-wide ones, before
you push.

---

## What happens after you send it

The maintainer merges the latest main into your branch, runs every test
suite on the result, and reads the change. For a provider, that means every
click, the guard, the download path, and the fixtures. Fixes the review
finds are usually applied on top of your work in a commit that says so,
and your commits stay yours. The pull request page shows what was changed
and why.

Merged work goes out with the next release, which is built by GitHub
Actions from a tag, on clean machines, for Windows and macOS. Your name
appears in the commit history and in the release notes for a new provider.

---

## When something goes wrong

**`git push` says permission denied to rheeloaded/paperpull.** You are
pushing to the original instead of your fork. `git remote -v` should show
`origin` as `YOUR-USERNAME/paperpull`. If it shows `rheeloaded`, you cloned
the original rather than your fork. Run
`git remote set-url origin https://github.com/YOUR-USERNAME/paperpull.git`.

**Git asks for a password and refuses the one you type.** GitHub does not
accept account passwords from Git. On Windows, Git for Windows opens a
browser sign-in the first time and remembers it. On macOS, install the
[GitHub CLI](https://cli.github.com/) and run `gh auth login`, which sets
Git up as well.

**`python` is not recognised.** On Windows, Python was installed without the
PATH box ticked. Reinstall and tick it, or use `py` instead of `python`. On
macOS use `python3`.

**`git status` shows my config.json or browser profile.** Do not commit.
Something removed those lines from `.gitignore` or the file is somewhere
unexpected. Open an issue describing what you see, without pasting the
file.

**The tests fail before I changed anything.** Pull the latest code first
(`git pull upstream main`). If they still fail, that is worth an issue on
its own, with the test name and the message.

**I made a mess of my branch.** Nothing on your branch can hurt the
original. `git checkout main`, make a new branch, and start the change
again. The old branch can sit there or be deleted.

**I'm stuck and none of this covers it.** Open an issue or ask on your
pull request. Saying where you are stuck is a fine contribution in itself.

---

## For maintainers, cutting a release

Versions follow [SemVer](https://semver.org). PATCH for fixes and site
repairs, MINOR for a new provider or a cross-app feature, MAJOR for a
breaking change to layout or config.

1. Bump `VERSION` and write the `CHANGELOG.md` entry.
2. Commit, push, then tag and push the tag:
   `git tag v0.20.0 -m "PaperPull 0.20.0" && git push origin v0.20.0`
3. The tag starts the Windows and macOS build workflows. Wait for both.
4. Download the artifacts from the two runs, check each file against the
   `SHA256SUMS.txt` its run published.
5. Create the GitHub release from the tag with notes that carry the
   checksums and link the two runs, and attach the files from the runs.
   Nothing built on a developer's machine goes on a release.
