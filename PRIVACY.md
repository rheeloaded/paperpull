# Privacy

This program does not transfer any information to other networked systems
unless specifically requested by the user.

That is the whole policy. The rest of this page says what it means in
practice, so you can check it against the code.

## What the program contacts

- **The providers you sign in to.** When you run a download, the program
  talks to that provider's website, and only that one, using the browser
  session you signed in with yourself. It reads your document list and
  fetches the PDFs the provider already generated. It never sends your
  password or a verification code anywhere, because it never has them. You
  type those into the provider's own page.
- **A browser download, once, if you agree.** If no usable browser is found
  on your computer, the sign-in step offers to download one from Playwright's
  release server. It asks on screen first and does nothing if you decline.
  If Edge, Chrome, Brave, Vivaldi or Opera is already installed, it uses that
  and never offers the download.

Nothing else. There is no update check, no crash reporting, no usage
statistics, no analytics, and no account with this project. The program has
no server of its own to talk to.

## What stays on your computer

Everything the program produces stays in the folders you chose.

- The PDFs it downloads.
- A record of what it has already downloaded, so it never fetches the same
  document twice, even after you delete the PDF.
- A browser profile per provider, holding that provider's signed-in session.
  This is the sensitive one. It lives next to that provider's downloads, and
  the program's setup and packaging both refuse to copy it anywhere.
- Logs and diagnostics, written only when you run a command, kept next to
  the downloads.

The control panel is a small local web server that listens on 127.0.0.1
only. It is not reachable from other machines and rejects requests that do
not come from your own browser on the same computer.

## What this project collects about you

Nothing. The project has no telemetry and no way to know you installed it.
GitHub, where the releases are hosted, has its own
[privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)
covering downloads from its site.

## Reporting a concern

If you find the program contacting anything not listed above, that is a bug
and a serious one. Open an issue or follow [SECURITY.md](SECURITY.md).
