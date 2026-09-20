# The website, paperpull.rhee.me

Static files, nothing else. `index.html`, `privacy.html`, one stylesheet
and the images under `img/`, which are the Store screenshots and the icon.
No build step, no framework, no analytics, no cookies. The one script on
the page asks GitHub's public releases API for the newest version so the
download buttons point straight at the installer, and falls back to the
Releases page if that call fails.

The Store button is off until the listing is live. Flip `STORE_LIVE` at
the top of the script in `index.html` when it is.

## Where it runs

A VPS that already serves other sites through a Caddy container
(`fluxer-edge-1`, ports 80 and 443). The site is one more host in that
Caddy's config, `Caddyfile.snippet` here, and a folder of files the
container can see. Caddy gets and renews the certificate on its own once
the DNS record points at the box.

## Deploying

```
site/deploy.sh
```

It copies this folder to the server with rsync (deletes on the server what
is no longer here) and asks Caddy to reload. It needs the `rheevps` SSH
host from `~/.ssh/config`. Nothing on the server is changed except the
site folder. The Caddy block is added once by hand, see the snippet.
