# Security, PaperPull Server

The desktop app listens on nothing your network can reach, see
[SECURITY.md](SECURITY.md). PaperPull Server does, by design, because you
use it from a browser on another computer. This page says what protects it,
and what is left to you.

Everything PaperPull itself does is as read-only as on the desktop. It
never moves money, changes a setting or submits a form beyond the one
exception the desktop page names, and every app keeps its host allowlist.
See "Design safety" in [SECURITY.md](SECURITY.md).

## The password

- **Chosen on the first visit.** Until there is a password, every page leads
  to one that asks for it, and that page wants a setup code the container
  prints in its log. So whoever reaches the page first on your network
  cannot choose it, only someone who can read the container's log, which is
  you. You can set it with `PAPERPULL_PASSWORD` in the environment instead.
- **Kept as a hash.** An scrypt hash in the `settings` volume, readable by
  the container's user only. The password itself is never written down.
- **Sessions.** Signing in gives your browser a random token in a cookie
  that the page's scripts cannot read and other sites cannot send. A
  session lasts 14 days, and ends sooner when the container restarts, the
  password changes, or you sign out. A Browser Screen left open closes
  within seconds of its session ending.
- **Wrong guesses wait.** After five wrong passwords or setup codes from one
  address, each next try waits, twice as long each time, up to a quarter of
  an hour.
- **Requests from other sites are refused,** even from a browser that is
  signed in, by checking that a request came from the panel's own page.
  The panel also answers only to its own names, the server's address, a
  home network name such as `nas` or `nas.local` and the names you list in
  `PAPERPULL_HOSTS`, see step 4 in [SERVER.md](SERVER.md), so a website
  cannot reach it through your browser by pointing a name of its own at
  your server. And no other site may show the panel inside a page of its
  own.
- **A forgotten password** is removed with
  `docker exec paperpull python /opt/paperpull/server/reset_password.py`,
  which signs everyone out.

## Treat it like a bank password

Whoever has the password can use every site you are signed in to on the
Browser Screen, as you. Choose one you use nowhere else, and keep it in your
password manager.

## Keep it on your home network

- **Never forward its port** on your router, and never put it on the open
  internet.
- **From outside,** reach it through your own VPN, such as WireGuard or
  Tailscale, into your home network.
- **HTTPS.** On your home network the panel speaks plain HTTP, like most
  things on a NAS. If its traffic crosses a network you do not trust, put it
  behind a reverse proxy that adds HTTPS, and list the name the proxy is
  reached by in `PAPERPULL_HOSTS`.
- **Rented servers** are not recommended, see "Where to run it" in
  [SERVER.md](SERVER.md).

## What runs inside the container

- **Not as root.** Everything runs as an ordinary user that takes your NAS
  user's ids, so the files it writes are yours and nothing more.
- **Chrome's sandbox stays on.** Chrome shuts every page it shows in a
  sandbox of its own. That needs the container to allow user namespaces,
  which Docker's default security profile forbids, and the usual workaround
  is to switch the profile off altogether, which leaves no filter at all.
  `server/seccomp-chrome.json` is instead Docker's own default profile with
  exactly two system calls allowed, `clone` with namespace flags and
  `unshare`, and nothing else changed (`server/seccomp.py` makes it).
  Never run the container with `seccomp=unconfined` or `privileged`.
- **Only the panel is on the network.** Each provider's browser debugging
  port and the screen sharing server listen inside the container only. The
  Browser Screen reaches you through the panel, behind the password, on the
  panel's one port.
- **Chrome keeps no passwords.** Its password manager and card autofill are
  switched off by policy, since a container's browser profile has no
  operating system keyring to protect them.

## Where your sign-ins live

Each provider account's signed-in browser profile is in the `profiles`
volume, kept out of the data folder, which is often a shared folder open to
other people. Anyone who can read that volume can act as you on those
sites, so back it up only somewhere as safe as your passwords, or not at
all, since you can always sign in again. Deleting the volume signs you out
everywhere at once.

## Reporting

The same way as for the desktop app, see [SECURITY.md](SECURITY.md).
