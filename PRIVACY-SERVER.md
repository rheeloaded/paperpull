# Privacy, PaperPull Server

This program does not transfer any information to other networked systems
unless specifically requested by the user.

That is the policy of the desktop app too, see [PRIVACY.md](PRIVACY.md).
This page says what it means on PaperPull Server, the edition you run on a
machine at home ([SERVER.md](SERVER.md)), so you can check it against the
code in `server/` and `gui/server_mode.py`.

## What the server contacts

- **The providers you sign in to.** When you run a download, the server
  talks to that provider's website, and only that one, in the browser you
  signed in with yourself in the sign-in window. It reads your document
  list and fetches the PDFs the provider already generated. It never has
  your password or a verification code, because you type those into the
  provider's own page.
- **Google, for Chrome.** Chrome is not in the image. The container
  downloads it from Google (`dl.google.com`) the first time it starts, and
  asks there for a newer one every time it starts.
- **Google, from Chrome itself,** for what Chrome does in any browser,
  checking pages against Safe Browsing and updating its own components.
  Usage statistics, sync, signing in to the browser, search suggestions,
  spell checking and translation are switched off by policy
  (`server/chrome-policies.json`).
- **Where you get the image from,** when you download or build it.
  Downloading it fetches it from GitHub's container registry (`ghcr.io`).
  Building it yourself downloads its parts from Debian, the Python Package
  Index and Google.
- **GitHub, to ask whether a newer version exists, only when you press the
  button.** The check is off until you turn it on in Settings, and turning
  it on sends nothing. Each press of **Check github.com for an update**
  sends one request from the server to `api.github.com` for this project's
  newest release. It carries no account, no document and no identifier of
  yours beyond what any web request reveals, such as the server's IP
  address, and its User-Agent says it is PaperPull's update check. Nothing
  is asked at the start or in the background. The server downloads nothing
  from it and never updates itself, since a container cannot replace its
  own image. It shows the steps that take the new one, which you run
  yourself (see "Updating" in [SERVER.md](SERVER.md)).

Nothing else. There is no crash reporting, no usage statistics, no
analytics, and no account with this project. The project runs no server of
its own for it to talk to.

## What stays on the server

Everything it produces stays on the machine you run it on, in the places
you gave the container.

- **The data folder.** The PDFs, the record of what was already downloaded,
  the spreadsheets, the logs and diagnostics.
- **The `profiles` volume.** A browser profile per provider account,
  holding that account's signed-in session. This is the sensitive one, and
  it is kept out of the data folder on purpose, since a shared folder is
  often open to more people than you.
- **The `settings` volume.** The password's hash, never the password, the
  panel's own settings and the sign-in window's logs.
- **The `browser` volume.** Chrome as Google sent it.

If you mount Paperless's consume folder, each run's new documents are also
copied there, and nowhere else.

**Export history** in Settings hands your browser a file listing
each provider and person, their settings and every document already
downloaded, and the server keeps no copy. A file you bring with **Import a
history file** is read, what it records is written into the data folder,
and the file itself is not kept.

## Who can reach it

Unlike the desktop app, the server listens on your home network, by
design. Apart from the page that asks for the password, every page, the
sign-in window and the panel's API answer only after it, see
[SECURITY-SERVER.md](SECURITY-SERVER.md).

## What this project collects about you

Nothing. The project has no telemetry and no way to know you run it.
GitHub, where the code is hosted, has its own
[privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)
covering what is downloaded from it.

## Reporting a concern

The same way as for the desktop app, see [PRIVACY.md](PRIVACY.md).
