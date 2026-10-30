# PaperPull Server

PaperPull for an always-on machine at home, such as a NAS
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
a Raspberry Pi cannot run it. Chrome's sandbox needs user namespaces and
seccomp from its kernel, which every common Linux has and some NAS kernels
lack, see [On Synology](#on-synology).

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

`compose.yaml` names the image a PaperPull release publishes, by that
release's version, such as `ghcr.io/rheeloaded/paperpull-server:0.59.2`,
and Docker downloads it from GitHub the first time the project starts.
Before a release publishes it, the image is built from that release's
code, started the way this page describes and checked, and only that very
image goes out. Each image comes with a signed list of everything inside
it, see "Its parts are listed and checked" in
[SECURITY-SERVER.md](SECURITY-SERVER.md).

`compose.https.yaml`, the setup with HTTPS, also names Caddy's own image,
`caddy` on Docker Hub, by its version, under Caddy's Apache-2.0 license.

If Docker cannot download it, no release has published that version yet.
A release's own `PaperPull-Server-X.Y.Z.zip` always names an image that
exists, while the copy in this repository names the next version for a
short while before its release goes out. Write the newest version on the
releases page in the `image:` line then, or build the image yourself, from
a checkout of this repository, on any computer with Docker and Python.

```bash
python server/build.py --save paperpull-server.tar
```

That builds `paperpull-server:dev` from the files git tracks, nothing else
from the folder, and writes it to a file you can import on the NAS. Write
`paperpull-server:dev` as the `image:` in `compose.yaml` to use it.
Building it downloads its parts from Debian, the Python Package Index and
Google.

## Set it up

There are two compose files. `compose.https.yaml` is the one to use. It
puts Caddy in front of the panel, so your browser reaches it by HTTPS and
nobody else on your network can read what you type into the panel or the
sign-in window, see [HTTPS](#https). `compose.yaml` serves the panel by
plain HTTP, as PaperPull Server always has, and keeps working for an
installation that uses it.

1. **Make a folder for it** on the server, and put `compose.https.yaml`,
   `Caddyfile` and `seccomp-chrome.json` in it, from
   `PaperPull-Server-X.Y.Z.zip` on the
   [newest release](https://github.com/rheeloaded/paperpull/releases/latest),
   or from `server/` in this repository. `Caddyfile` holds Caddy's
   settings, and needs no changes. `seccomp-chrome.json` is the
   container's security profile, see "Chrome's sandbox" in
   [SECURITY-SERVER.md](SECURITY-SERVER.md). For plain HTTP, put
   `compose.yaml` and `seccomp-chrome.json` there instead.
2. **Fill in the compose file.** At least these.
   - `PUID` and `PGID`, the ids of the NAS user your documents should
     belong to. Your NAS shows them, or run `id` over SSH.
   - `TZ`, your time zone.
   - The data folder, `./data` unless you point it at a shared folder.
   - In `compose.https.yaml`, `x-address`, the server's address on your
     home network, and `x-names`, any names you open it by, see
     [HTTPS](#https).
   - If you use Paperless, its consume folder, see [Paperless](#paperless).
   - If the server has Intel or AMD graphics, the two `devices` lines,
     see [Graphics](#graphics).
3. **Start it.**
   ```bash
   docker compose -f compose.https.yaml up -d
   ```
   With `compose.yaml`, `docker compose up -d` alone.
4. **Choose a password.** With `compose.https.yaml`, first have the device
   trust Caddy's certificate authority, see
   [Trust Caddy's certificate authority](#trust-caddys-certificate-authority),
   then open `https://<the server's address>:8765` in a browser on your
   home network. With `compose.yaml`, open
   `http://<the server's address>:8765`. The first visit asks you to choose
   a password, with a setup code the container prints in its log.
   ```bash
   docker logs paperpull
   ```
   The panel answers to the server's address and to a name that exists
   only on a home network, one without a dot such as `nas`, or one ending
   in `.local`, `.lan`, `.home`, `.home.arpa`, `.internal` or
   `.localdomain`. To reach it
   by any other name, a VPN's or a reverse proxy's, list that name in
   `PAPERPULL_HOSTS` in `compose.yaml`, more than one separated by commas.
   With `compose.https.yaml` it is the address and names in `x-address`
   and `x-names`, since Caddy has a certificate for those alone.

   To have it answer to nothing you did not list, set `PAPERPULL_HOSTS_ONLY`
   to `1` beside `PAPERPULL_HOSTS`. It then answers only to the names and
   addresses in `PAPERPULL_HOSTS`, and no longer to its address or a home
   network name unless you list them too, so list the address or name you
   open it by. The container still reaches itself by its own loopback,
   which the self-test uses. With `compose.https.yaml`, put the address in
   `x-names` as well. A name it refuses gets a page saying the setting is
   on and how to add the name, and when nothing is listed the container's
   log says so at start and the self-test's network row fails.
5. **Add your providers** from the panel. Each one gets a folder in the data
   folder. Coming from the desktop app, bring them instead, see
   [Coming from the desktop app](#coming-from-the-desktop-app).
6. **Sign in.** Open a provider and press **Open sign-in window**. Its
   sign-in page opens in the sign-in window, the browser on the server's
   screen, docked beside the panel. The **Sign-in window** button at the
   top opens it at any time, and Full screen gives it a tab of its own.
   Sign in there as you would on a new computer, press **Done** to put the
   window aside, then **Try the newest few first** and **Get new
   documents**.

### Coming from the desktop app

Bring your providers and the record of what they already downloaded, so
the server does not download those documents again, or hand them to
Paperless a second time.

1. On the desktop, open the panel's **Settings** and press **Export
   history**. Your browser saves a file named like
   `PaperPull history 2026-10-11.ppz`.
2. On the server's welcome page, choose **Moving from another computer?
   Bring its providers and history**, then that file. The panel shows what
   it will do, and **Set up and import** does it. Once providers are set
   up, the same is under **Import a history file** in Settings.

Each provider and person in the file is set up with their settings, the
account holder's name, file name patterns, the start date and the like,
and every document they already downloaded is marked as downloaded.
Folders, browser profiles and debugging ports are the server's own. A
provider or person already set up keeps its settings and gains only the
history. No sign-in comes with the file, so sign in to each provider in the
sign-in window, as in step 6.

The file holds no password, sign-in or PDF. It does list document titles,
order numbers, totals and the account holders' names, so keep it as
private as your documents. The PDFs can stay where they are, since the
record is all the server needs to skip them.

### On a UGREEN NAS

The labels in the UGOS Docker app may differ a little from these.

1. Put `compose.https.yaml`, `Caddyfile` and `seccomp-chrome.json` in a
   shared folder of their own, and fill in `compose.https.yaml` as above.
   UGOS shows your user's `PUID` and `PGID` above the compose editor.
2. Open **Project**, create one with that folder as its path, and paste or
   import `compose.https.yaml`. Leave **Run immediately after creation**
   ticked. The Docker app downloads the images itself.
3. The setup code is in the container's log. Open the `paperpull` container
   in the Docker app and look at its log. Caddy's certificate authority is
   copied out over SSH, as in
   [Trust Caddy's certificate authority](#trust-caddys-certificate-authority),
   with `sudo` in front.

With an image you built yourself, import `paperpull-server.tar` first. In
the Docker app, open **Image** and choose to add or import a local image.

### On Unraid

A tester ran it on Unraid 7.3.3 with the Compose Manager plugin, from
Community Applications.

1. Put `compose.https.yaml`, `Caddyfile` and `seccomp-chrome.json`
   together in a folder of their own, such as `/mnt/user/appdata/paperpull`,
   and fill in `compose.https.yaml` as above.
2. Write the three paths in `compose.https.yaml` that start with `./` as
   absolute paths to that folder,
   `seccomp=/mnt/user/appdata/paperpull/seccomp-chrome.json`,
   `/mnt/user/appdata/paperpull/data:/data` and
   `/mnt/user/appdata/paperpull/Caddyfile:/etc/caddy/Caddyfile:ro`.
3. In Compose Manager, add a new stack, paste `compose.https.yaml` into it
   and start it with Compose Up. The setup code is in the container's log.

### On Synology

Chrome builds its sandbox from user namespaces and seccomp, and PaperPull
never starts Chrome without its sandbox, since the sign-in windows hold your
bank sessions. Synology DSM's kernels lack one or both, so check yours over
SSH before anything else. `uname -r` shows which kernel it is.

```bash
grep Seccomp /proc/self/status
```

```bash
cat /proc/sys/user/max_user_namespaces
```

- **No `Seccomp` line.** The kernel has no seccomp, as Synology's 4.4
  kernels, which many models still run under DSM 7, are built, and none of
  them has user namespaces either. PaperPull Server cannot run on DSM
  itself there. No sign-in window opens and the Browser Screen stays
  black. The container's log says so in a line that starts with
  `[sandbox]`, and the panel says so at the top of every page. Docker also
  refuses the container's security profile there, saying seccomp is not
  enabled in your kernel. Removing `security_opt` gets the container
  started, but PaperPull still starts no Chrome on a kernel without
  seccomp, not even one that has user namespaces, since Chrome would run
  there with only half its sandbox. The panel stays up and says why, and
  so does a sign-in. Use one of the two ways below.
- **A `Seccomp` line and a number above `0`.** The setup above works as it
  is.
- **A `Seccomp` line, and a `0` or "No such file or directory".** The kernel
  has seccomp but no user namespaces, so Chrome's usual sandbox cannot
  start. Chrome's setuid sandbox builds the same first layer without them,
  and two lines in the compose file turn it on. It is not `--no-sandbox`,
  and Chrome still never starts without its whole sandbox.

  **Know what you turn on.** It costs something, and the risk is small but
  real. `SYS_ADMIN` is the broadest of Linux's powers, and the container
  holds it for as long as it runs. No page ever gets it. Chrome's setuid
  helper uses it only while it builds a page's sandbox, and gives it up
  before the page runs. But anything that became root inside the container
  could use it to reach much further into your NAS than a container
  otherwise can, and the helper is itself a program that runs as root, so
  a flaw in it would be one way to that root. Getting there would first
  take running code inside the container, by escaping Chrome's sandbox or
  getting past the panel's password, and then becoming root, which is why
  the risk is small. It also rules out `no-new-privileges`, another guard
  Docker offers. Turn it on only on a kernel that needs it. The trade in
  full is under "Chrome's sandbox stays on" in
  [SECURITY-SERVER.md](SECURITY-SERVER.md).

  If you take it, remove the `#` from the two `cap_add` lines under
  `security_opt` in `compose.https.yaml`, so that they read
  ```yaml
      cap_add:
        - SYS_ADMIN
  ```
  and recreate the container with
  `sudo docker compose -f compose.https.yaml up -d`, or from Container
  Manager. The container's log then says Chrome's setuid sandbox helper is
  set up, or why it is not, and the self-test's `sandbox` line says
  `layer 1 SUID, seccomp on`. This has not been seen on a Synology yet, so
  tell us how it goes.

Where PaperPull Server cannot run on DSM itself, two ways work on a
Synology NAS.

- **A Linux virtual machine.** If your model has Synology Virtual Machine
  Manager, make a Debian 12 virtual machine there, install Docker in it,
  and set up PaperPull Server inside it as above. Debian 12's kernel has
  user namespaces and seccomp both. This has not been tried on a Synology
  yet.
- **The desktop app**, on a computer of your own.

At each start, a container given `SYS_ADMIN` on a kernel with seccomp has
the helper of the Chrome in use made setuid root, so Chrome never gets half
its sandbox through it, and any other container has the bit taken off every
copy, so removing the two lines again undoes it. The helper is set up only
where root alone could have put it, a plain file of root's with one name,
in folders of root's that nobody else may write to and that are not links,
from `/browser` down. That is why the `browser` volume belongs to root, and a
volume made by an older image has its top folder given back to root at the
start. Where any of that does not hold, the helper is not set up and the
container's log says why. `SYS_ADMIN` lets the helper build the sandbox's
own namespaces and chroot. It is given to the container, never to the
pages, and the helper gives up every privilege before a page runs. Never
put `privileged` or `--no-sandbox` in its place, which would leave no
sandbox at all. Leave `no-new-privileges` off this container, since
it turns the setuid bit off, and for the same reason keep the `browser`
volume on a file system mounted without `nosuid`, as Docker's own volumes
are.

## HTTPS

Over plain HTTP, anyone else on your network can read what passes between
your browser and the panel, your password as you sign in and everything you
type in the sign-in window, a provider's password included. A guest network,
or any device on yours you do not trust, is reason enough to use HTTPS.

`compose.https.yaml` is the same server with Caddy in front of it. Caddy
answers by HTTPS on port 8765, with a certificate from a certificate
authority it makes for itself at its first start, and passes each request
on to the panel. The sign-in window travels over that same connection. The
panel itself is published on no port, so your network is offered no plain
HTTP to it, and the sign-in cookie is one that travels over HTTPS only. It is the same project as `compose.yaml`, with the same
volumes, so your password, sign-ins and settings stay the same.

### Trust Caddy's certificate authority

A browser trusts a certificate only from an authority it knows, so each
device you open the panel from has to know Caddy's, once. Copy it out of the
container on the server, then copy the file to each device yourself, never
from a link someone sent you.

```bash
docker cp paperpull-proxy:/data/caddy/pki/authorities/local/root.crt paperpull-root.crt
```

Then add `paperpull-root.crt` to each device's trusted authorities. The
labels differ a little between versions.

- **Windows.** Double-click the file, choose **Install Certificate**, then
  **Current User**, then **Place all certificates in the following store**,
  and choose **Trusted Root Certification Authorities**.
- **Mac.** Double-click the file to add it to your login keychain, open
  **Caddy Local Authority** in Keychain Access, and under **Trust** choose
  **Always Trust**.
- **iPhone and iPad.** Open the file on the device and install the profile
  in Settings, then turn on full trust for it in **Settings**, **General**,
  **About**, **Certificate Trust Settings**.
- **Android.** **Settings**, **Security**, **Encryption and credentials**,
  **Install a certificate**, **CA certificate**.
- **Firefox** may keep a list of its own. Import the file under
  **Settings**, **Privacy & Security**, **Certificates**, **View
  Certificates**, **Authorities**.

The authority lasts ten years, and Caddy renews the panel's own
certificate by itself. Its key is in the `proxy-data` volume, and whoever
has that key can make certificates your devices trust for any website. So
keep that volume out of shared folders and out of backups others can read.
If it may have been copied, see "If something may have been exposed" in
[SECURITY-SERVER.md](SECURITY-SERVER.md).

### Its names

`x-address` is the server's address on your home network, the one you
would open `http://<address>:8765` by, and `x-names` any names you open it
by as well, such as `nas.local`, more than one separated by spaces. Caddy
makes a certificate for each and for nothing else, so open the panel by
one of them. After changing either, run
`docker compose -f compose.https.yaml up -d` again.

### Moving to HTTPS

An installation that runs `compose.yaml` keeps everything when it moves. In
its folder, put `compose.https.yaml` and `Caddyfile` beside `compose.yaml`,
fill in `compose.https.yaml` the way `compose.yaml` is filled in, with
`x-address` and `x-names` besides, then stop the old one and start the new.

```bash
docker compose down
docker compose -f compose.https.yaml up -d
```

On a NAS's Docker app, replace the project's compose file with your
`compose.https.yaml`, put `Caddyfile` in the project's folder, and redeploy
the project. The old address, `http://<address>:8765`, then answers that
the browser sent plain HTTP to an HTTPS server, so open
`https://<address>:8765`. From then on the commands on this page take
`-f compose.https.yaml`, `docker compose -f compose.https.yaml pull` when
updating for instance.

### A reverse proxy of your own

If you already run one, keep `compose.yaml` and put the panel behind it,
as "HTTPS" in [SECURITY-SERVER.md](SECURITY-SERVER.md) describes.

## Graphics

The sign-in window runs on a virtual screen inside the container, which has
no graphics of its own. Without a graphics chip, Chrome draws every page in
software and turns WebGL off, and some sites take that for an automated
browser. Best Buy refuses the sign-in outright, rejecting a correct password
and every code, or dropping the connection with `ERR_HTTP2_PROTOCOL_ERROR`.

So when the server has Intel or AMD graphics, pass them to the container.
In `compose.yaml`, remove the `#` from these two lines under `shm_size`, then
recreate the container with `docker compose up -d`.

```yaml
    devices:
      - /dev/dri:/dev/dri
```

- **Check it.** Run `ls /dev/dri` on the server first. It should list
  `card0` and `renderD128`. Without them, leave the lines out, since Docker
  will not start a container that names a missing device.
- **See that it took.** Open `chrome://gpu` in the sign-in window. The
  graphics should read hardware accelerated, with an Intel or AMD chip named
  under GPU0, not `llvmpipe`. The self-test says the same, on its graphics
  line.
- **Which machines.** Intel graphics from Broadwell on, which covers most
  Intel NAS boxes, works, measured on a UGREEN NAS. AMD graphics should work
  and has not been tried. NVIDIA is not covered, and a machine with no
  graphics chip, such as Synology's AMD Ryzen models, draws in software as
  before.
- **In a NAS's Docker app.** The project's compose file is the one to edit.
  If the app keeps a copy of its own, edit it there and redeploy the project.
- To turn it off without editing the file, set `PAPERPULL_GPU: "off"` under
  `environment`.

## Paperless

Point a volume at Paperless's consume folder, and after every run the
documents that run saved are copied into it.

```yaml
    volumes:
      - /path/to/paperless/consume:/paperless
```

- **Copied, never moved.** PaperPull keeps its own files and its record of
  what it downloaded. Deleting them later never makes it download a
  document again. The desktop panel's Restore deleted files is not
  offered here, since every document it fetched would reach Paperless a
  second time.
- **Only what that run saved.** A run that saved nothing copies nothing,
  and a run that stopped early does not hand over the last run's documents
  a second time.
- **Never half a file.** Each copy is written under a hidden name and then
  renamed, and Paperless skips hidden names.
- **Renaming afterward stays in PaperPull.** Rename existing files and
  Review names rename PaperPull's own copies. A document already copied to
  Paperless keeps the title it has there, and is not copied again.
- **A folder per provider, if you like.** With `PAPERLESS_SUBFOLDERS: "1"`
  in the environment, each provider's documents go in a folder of that
  provider's name inside the consume folder. Paperless turns those folders
  into tags when `PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS` is on in Paperless.
- **A documents folder stays inside /data.** The panel's Documents folder
  setting works on the server for a folder inside the data folder, the
  folder for every provider and each provider's folder in it included, and
  a run's checked documents move there once the plug-ins have copied them.
  The panel refuses one anywhere else, or one reached through a link out
  of /data, and so does a run before it saves anything, so Paperless gets
  new documents through the volume above rather than through a documents
  folder.

What happened is in each run's output, a line such as "Copied 3 new
documents to Paperless".

## Signing in on the server

- **Pasting a password.** Open noVNC's side panel, the small tab on the left
  edge of the sign-in window, paste into its clipboard box, then press
  Ctrl+V in the page. Chrome on the server does not save passwords, so keep
  them in your own password manager.
- **A correct password or code refused**, or `ERR_HTTP2_PROTOCOL_ERROR`,
  usually means the site took the server's browser for an automated one,
  because it has no graphics. See [Graphics](#graphics).
- **"Robot or human?"** Some providers check, especially Walmart. Press and
  hold the button in the sign-in window yourself. PaperPull never answers
  one for you.
- **The sign-in window asks for your password again** when you open it
  more than 15 minutes after typing the password or last using the window,
  since it is live control of every site you are signed in to there. Your
  browser's password manager can fill it in. One left open closes 15
  minutes after it was opened or last had a key pressed or the mouse moved
  on it, and says so. The panel signs you out after eight hours without
  use, and then shows its sign-in page.
- **How long you stay signed in** depends on the provider. In testing, Best
  Buy stayed signed in for more than a day and through a restart, Verizon
  for more than a day but not through a restart, and T-Mobile and Navy
  Federal for less than half an hour. A restart of the server signs you out
  of any site that keeps its session only while the browser runs.

## Updating, backing up and removing

- **Updating.** Write the newer version in the `image:` line of
  `compose.yaml`, the number on the
  [releases page](https://github.com/rheeloaded/paperpull/releases), then
  run `docker compose pull` and `docker compose up -d` in the project's
  folder, or do the same from your NAS's Docker app. Everything you set up
  is in the volumes and stays. To go back, write the version you had and
  run the same two commands. Chrome brings itself up to date at every
  start. If you would rather take every release without editing the file,
  write `latest` in place of the version, which always names the newest
  release, and then the two commands alone update it. With
  `compose.https.yaml`, add `-f compose.https.yaml` to both commands. Its
  `caddy` image line names Caddy's version, which you update the same way.
- **Backing up.** Your documents are in the data folder. The `profiles`
  volume holds your live sign-ins, so a backup of it is as sensitive as your
  passwords, and you can always sign in again instead. The `settings` volume
  holds the password's hash and the panel's own settings. With HTTPS, the
  `proxy-data` volume holds Caddy's certificate authority, so keep it out
  of any backup others can read. Without it, Caddy makes a new authority,
  and each device has to trust the new one.
- **A forgotten password.** This signs everyone out, and the next visit asks
  for a new password with a new setup code.
  ```bash
  docker exec paperpull python /opt/paperpull/server/reset_password.py
  ```
- **Removing it.** Delete the project, then its volumes, the `profiles`
  volume above all, since it holds live sign-ins, and with HTTPS the
  `proxy-data` volume, then take Caddy's authority off each device that
  trusted it. The data folder is yours and stays where it is.

## When something is wrong

Run the self-test. It checks Chrome, its sandbox, the screen, printing, the
password gate and what is reachable from the network, and says what failed.

```bash
docker exec paperpull python /opt/paperpull/server/selftest.py
```

- **Chrome does not start.** Read the self-test's `sandbox` line, or the
  line near the top of the container's log that starts with `[sandbox]`.
  Both say whether this host can give Chrome its sandbox, and why not.
  - If the container may not make user namespaces, the security profile is
    probably not applied. Check that `seccomp-chrome.json` sits next to
    `compose.yaml` and that `security_opt` names it. Docker's default
    profile stops Chrome's sandbox, see
    [SECURITY-SERVER.md](SECURITY-SERVER.md).
  - If the host's kernel has no user namespaces, Chrome's usual sandbox
    cannot start on it, see [On Synology](#on-synology), which also says
    when Chrome's setuid sandbox can stand in.
  - If the host's kernel has no seccomp-bpf filter, PaperPull does not
    start Chrome at all, and a sign-in says Chrome was not started. Chrome
    would run there with only the namespace half of its sandbox, and
    nothing can stand in for the filter, so use another host, see
    [On Synology](#on-synology).
- **The first start ends at once.** It needs to reach `dl.google.com` once
  to download Chrome. After that it starts without a connection and uses
  the Chrome it has.
- **The panel does not load.** Check that nothing else uses port 8765 on the
  server, or publish the panel on another port in `compose.yaml`, or Caddy
  on another in `compose.https.yaml`.
- **The browser says the connection is not private.** The device does not
  trust Caddy's certificate authority yet, see
  [Trust Caddy's certificate authority](#trust-caddys-certificate-authority),
  or the panel was opened by an address or name that is not in `x-address`
  or `x-names`.
- **The panel says it was asked for by a name that is not one of its
  names.** It answers only to the names in step 4 of the setup, so that a
  website cannot reach it through your browser by pointing a name of its
  own at your server. Add the name you use to `PAPERPULL_HOSTS` in
  `compose.yaml`, or to `x-names` in `compose.https.yaml`, then recreate
  the container, with `docker compose up -d` or from your NAS's Docker
  app, as when updating.
- **A file to attach to an issue.** After a run that stops early, a support
  report or a recording, the run's page offers its file to download, where
  the desktop opens the folder. Each is built from PaperPull's fixed word
  list and holds no text from your account. A screenshot Diagnose takes
  stays on the server.
- **Documents set aside.** A run that would not file a document under a
  name it could be wrong about puts it in the account's Manual Review
  folder. The run's page offers what is there as one zip.

## Where the provider code runs

On PaperPull Server the provider code comes from the image. When you add a
provider, its folder in the data folder holds your configuration, your
rules file, the documents it downloads and its records, but not the code
that runs. The code, the Python interpreter and the modules a run imports
all come from the read-only application folder inside the container. So
editing a provider's script under the data folder, or putting a Python
virtual environment in its folder, changes nothing on the server, since the
server runs the image's copy. This keeps the code the server runs as you
out of reach of anyone who can write to a shared data folder. See
[SECURITY-SERVER.md](SECURITY-SERVER.md) for the trust boundary and why
write access to the data share should be yours alone.

## What is in the image

Debian's slim Python image, the virtual screen (Xvfb), a window manager
(Fluxbox), the screen sharing server (x11vnc), noVNC's web page for it, and
PaperPull. Their licenses are in the image under `/usr/share/doc`.
PaperPull is AGPL-3.0, and the container's security profile is Apache-2.0,
see [NOTICE.md](NOTICE.md). Chrome is not in the image. The container
downloads it from Google, under Google's own terms, the first time it
starts.
