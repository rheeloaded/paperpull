# PaperPull Server

**Experimental.** PaperPull for an always-on machine at home, such as a NAS
or a home server, used from a browser on any computer on your home network.
It is meant to sit next to [Paperless-ngx](https://docs.paperless-ngx.com/),
so the documents PaperPull collects can go straight into it.

It is the same PaperPull with the same limits. It does not sign in for you.
You sign in to each provider yourself, on a browser screen the server shows
in your browser, and a bank that signs you out after a few minutes needs
you there again next time, as it would on the desktop. It does not run on a
schedule yet. You start each run from the panel.

It has privacy and security pages of its own, [PRIVACY-SERVER.md](PRIVACY-SERVER.md)
and [SECURITY-SERVER.md](SECURITY-SERVER.md), because unlike the desktop app
it listens on your network.

## Where to run it

On your home network, on a machine with Docker and an Intel or AMD
processor. Google publishes no Chrome for ARM Linux, so ARM machines such as
a Raspberry Pi cannot run it.

- **Memory.** About 120 MB with no sign-in window open. Each provider's
  window you leave open adds a few hundred MB, and Chrome grows the longer
  they stay open. In testing on a NAS, three providers' windows took about
  1.3 GB after a start and about 3 GB a day later. Plan on 4 GB free if you
  keep several open.
- **Disk.** About 1.3 GB for the image and 450 MB for Chrome, twice that
  once Chrome has updated, since the version before is kept. Plus your
  documents.

> **Not on a rented server.** A VPS or any server in a data center can run
> PaperPull Server, but providers treat data-center addresses as likely
> bots. Expect far more "Robot or human?" checks than at home, and some
> sites refusing to let you in at all. It is made for a machine at home.

## Get the image

`compose.yaml` names the image every PaperPull release publishes,
`ghcr.io/rheeloaded/paperpull-server:latest`, and Docker downloads it from
GitHub the first time the project starts. Before a release publishes it,
the image is built from that release's code, started the way this page
describes and checked, and only that very image goes out.

If Docker cannot download it, no release has published it yet. Build it
yourself then, from a checkout of this repository, on any computer with
Docker and Python.

```bash
python server/build.py --save paperpull-server.tar
```

That builds `paperpull-server:dev` from the files git tracks, nothing else
from the folder, and writes it to a file you can import on the NAS. Write
`paperpull-server:dev` as the `image:` in `compose.yaml` to use it.
Building it downloads its parts from Debian, the Python Package Index and
Google.

## Set it up

1. **Make a folder for it** on the server, and copy `server/compose.yaml`
   and `server/seccomp-chrome.json` from this repository into it. The second
   file is the container's security profile, see "Chrome's sandbox" in
   [SECURITY-SERVER.md](SECURITY-SERVER.md).
2. **Fill in `compose.yaml`.** At least these.
   - `PUID` and `PGID`, the ids of the NAS user your documents should
     belong to. Your NAS shows them, or run `id` over SSH.
   - `TZ`, your time zone.
   - The data folder, `./data` unless you point it at a shared folder.
   - If you use Paperless, its consume folder, see [Paperless](#paperless).
3. **Start it.**
   ```bash
   docker compose up -d
   ```
4. **Choose a password.** Open `http://<the server's address>:8765` in a
   browser on your home network. The first visit asks you to choose a
   password, with a setup code the container prints in its log.
   ```bash
   docker logs paperpull
   ```
5. **Add your providers** from the panel. Each one gets a folder in the data
   folder.
6. **Sign in.** Pick a provider and press Login. Its sign-in window opens on
   the browser screen, which the **Browser screen** link at the top of the
   panel opens. Sign in there as you would on a new computer, then come back
   to the panel and run Pilot, then Run All.

### On a UGREEN NAS

The labels in the UGOS Docker app may differ a little from these.

1. Put `compose.yaml` and `seccomp-chrome.json` in a shared folder of their
   own, and fill in `compose.yaml` as above. UGOS shows your user's
   `PUID` and `PGID` above the compose editor.
2. Open **Project**, create one with that folder as its path, and paste or
   import `compose.yaml`. Leave **Run immediately after creation** ticked.
   The Docker app downloads the image itself.
3. The setup code is in the container's log. Open the `paperpull` container
   in the Docker app and look at its log.

With an image you built yourself, import `paperpull-server.tar` first. In
the Docker app, open **Image** and choose to add or import a local image.

Synology and Unraid should work the same way and have not been tried yet.

## Paperless

Point a volume at Paperless's consume folder, and after every run the
documents that run saved are copied into it.

```yaml
    volumes:
      - /path/to/paperless/consume:/paperless
```

- **Copied, never moved.** PaperPull keeps its own files and its record of
  what it downloaded. Deleting them later never makes it download a
  document again.
- **Only what that run saved.** A run that saved nothing copies nothing,
  and a run that stopped early does not hand over the last run's documents
  a second time.
- **Never half a file.** Each copy is written under a hidden name and then
  renamed, and Paperless skips hidden names.
- **A folder per provider, if you like.** With `PAPERLESS_SUBFOLDERS: "1"`
  in the environment, each provider's documents go in a folder of that
  provider's name inside the consume folder. Paperless turns those folders
  into tags when `PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS` is on in Paperless.

What happened is in each run's output, a line such as "Copied 3 new
documents to Paperless".

## Signing in on the browser screen

- **Pasting a password.** Open noVNC's side panel, the small tab on the left
  edge of the browser screen, paste into its clipboard box, then press
  Ctrl+V in the page. Chrome on the server does not save passwords, so keep
  them in your own password manager.
- **"Robot or human?"** Some providers check, especially Walmart. Press and
  hold the button on the browser screen yourself. PaperPull never answers
  one for you.
- **How long you stay signed in** depends on the provider. In testing, Best
  Buy stayed signed in for more than a day and through a restart, Verizon
  for more than a day but not through a restart, and T-Mobile and Navy
  Federal for less than half an hour. A restart of the server signs you out
  of any site that keeps its session only while the browser runs.

## Updating, backing up and removing

- **Updating.** Download the newer image and recreate the container, with
  `docker compose pull` and then `docker compose up -d` in the project's
  folder, or the same from your NAS's Docker app. Everything you set up is
  in the volumes and stays. Chrome brings itself up to date at every start.
- **Backing up.** Your documents are in the data folder. The `profiles`
  volume holds your live sign-ins, so a backup of it is as sensitive as your
  passwords, and you can always sign in again instead. The `settings` volume
  holds the password's hash and the panel's own settings.
- **A forgotten password.** This signs everyone out, and the next visit asks
  for a new password with a new setup code.
  ```bash
  docker exec paperpull python /opt/paperpull/server/reset_password.py
  ```
- **Removing it.** Delete the project, then its volumes, the `profiles`
  volume above all, since it holds live sign-ins. The data folder is yours
  and stays where it is.

## When something is wrong

Run the self-test. It checks Chrome, its sandbox, the screen, printing, the
password gate and what is reachable from the network, and says what failed.

```bash
docker exec paperpull python /opt/paperpull/server/selftest.py
```

- **Chrome does not start.** The security profile is probably not applied.
  Check that `seccomp-chrome.json` sits next to `compose.yaml` and that
  `security_opt` names it. Docker's default profile stops Chrome's sandbox,
  see [SECURITY-SERVER.md](SECURITY-SERVER.md).
- **The first start ends at once.** It needs to reach `dl.google.com` once
  to download Chrome. After that it starts without a connection and uses
  the Chrome it has.
- **The panel does not load.** Check that nothing else uses port 8765 on the
  server, or publish the panel on another port in `compose.yaml`.

## What is in the image

Debian's slim Python image, the virtual screen (Xvfb), a window manager
(Fluxbox), the screen sharing server (x11vnc), noVNC's web page for it, and
PaperPull. Their licenses are in the image under `/usr/share/doc`.
PaperPull is AGPL-3.0, and the container's security profile is Apache-2.0,
see [NOTICE.md](NOTICE.md). Chrome is not in the image. The container
downloads it from Google, under Google's own terms, the first time it
starts.
