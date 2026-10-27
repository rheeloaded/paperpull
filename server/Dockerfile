# PaperPull Server. The panel and the apps in one container, with a virtual
# screen for the providers' sign-in browsers, shown through a web page.
#
# Built from the repository root by server/build.py, which hands Docker the
# files git tracks and nothing else, so no download, record or browser
# profile in a working copy can reach the image.
#
# Chrome is not in the image. The container downloads it from Google when it
# starts and keeps it up to date in its own volume (server/chrome.sh), so
# Google's browser is never redistributed here and its security fixes arrive
# without a new image.
#
# The base is named by its digest as well as its tag, so every build starts
# from the very same files, whatever the tag points at that day. A frozen
# base stops getting Debian's fixes, so Dependabot proposes the tag's new
# digest each week (.github/dependabot.yml), and the Server image workflow
# builds, starts and scans the image on that proposal before it can merge.
# By hand, `python server/lock.py --base` writes the tag's current digest.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# The virtual screen, its window manager and the screen sharing server, the
# fonts receipts are printed in, and gpg for checking Google's signing key.
#
# noVNC, the page that shows the screen, is only web files, so they are
# taken out of Debian's package without installing it. Installed, it would
# bring Node.js and NumPy, about 90 MB the image never uses. The panel
# carries noVNC's connection itself (gui/server_mode.py), so websockify is
# not needed either.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tzdata procps \
      xvfb fluxbox x11vnc \
      mesa-vulkan-drivers libvulkan1 libgl1-mesa-dri libegl1 libgles2 \
      fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
 && cd /tmp && apt-get download novnc \
 && dpkg-deb -x novnc_*.deb /tmp/novnc \
 && mv /tmp/novnc/usr/share/novnc /usr/share/novnc \
 && mkdir -p /usr/share/doc/novnc \
 && cp /tmp/novnc/usr/share/doc/novnc/copyright /usr/share/doc/novnc/ \
 && rm -rf /tmp/novnc /tmp/novnc_*.deb /var/lib/apt/lists/* \
 && test -f /usr/share/novnc/vnc.html

# Google's package list and signing key, checked against the fingerprint
# Google publishes at google.com/linuxrepositories, so apt verifies every
# Chrome package the container downloads. Chrome's package is installed here
# only so apt brings in the libraries Chrome needs, then removed in the same
# step, which leaves the libraries and no browser in the image.
ARG GOOGLE_SIGNING_FINGERPRINT=EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub -o /tmp/google.pub \
 && gpg --show-keys --with-colons /tmp/google.pub | grep -q "^fpr:::::::::${GOOGLE_SIGNING_FINGERPRINT}:" \
 && gpg --dearmor -o /usr/share/keyrings/google-linux.gpg /tmp/google.pub \
 && rm /tmp/google.pub \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/paperpull-chrome.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends google-chrome-stable \
 && apt-mark manual $(apt-mark showauto) >/dev/null \
 && apt-get purge -y google-chrome-stable \
 && rm -f /etc/apt/sources.list.d/google-chrome.list /etc/cron.daily/google-chrome \
 && rm -rf /opt/google /var/lib/apt/lists/* \
 && test ! -e /usr/bin/google-chrome-stable

# Chrome's settings for this container, read from the place Chrome reads
# managed policies. No usage reports, no sync, no browser sign-in.
COPY server/chrome-policies.json /etc/opt/chrome/policies/managed/paperpull.json

# The name the apps look for (paperpull_core.browser lists it), pointing at
# the Chrome the container downloaded into its volume.
RUN printf '#!/bin/sh\nexec /browser/current/opt/google/chrome/google-chrome "$@"\n' \
      > /usr/bin/google-chrome-stable \
 && chmod 755 /usr/bin/google-chrome-stable

# Every package at the version server/lock.py wrote, each file checked
# against its hash, and only built wheels, so nothing runs a package's own
# build step. pip refuses a package the lock does not name.
COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The user everything runs as. Its ids follow PUID and PGID at start, so the
# files it writes into a shared folder belong to the person's own NAS user.
# /browser stays root's, and a new volume takes its owner from here, since
# pp only reads Chrome and chrome.sh, which runs as root, writes it.
RUN useradd --create-home --uid 1000 pp \
 && mkdir -p /data /profiles /config /browser \
 && chown pp:pp /data /profiles /config

# The user and group files as the image makes them are kept in
# /etc/paperpull. The entrypoint writes the ones in use from them into
# /run/paperpull at every start, with pp given PUID and PGID, and
# /etc/passwd and /etc/group are links there, so the ids can change while
# the image's own files stay read-only (read_only in the compose files).
# Docker itself looks up a user or group it is given by name, in a compose
# file's user or group_add or with `docker exec -u`, in the image's own
# files rather than in a /run kept in memory. So the image keeps copies in
# /run/paperpull without pp, where Docker finds root, video and the rest,
# and finds no pp, who there would have the image's 1000 rather than PUID.
# The entrypoint writes over them, and a /run in memory hides them.
RUN mkdir -p /etc/paperpull /run/paperpull \
 && cp /etc/passwd /etc/group /etc/paperpull/ \
 && mv /etc/passwd /etc/group /run/paperpull/ \
 && ln -s /run/paperpull/passwd /etc/passwd \
 && ln -s /run/paperpull/group /etc/group \
 && id pp \
 && grep -v '^pp:' /etc/paperpull/passwd >/run/paperpull/passwd \
 && grep -v '^pp:' /etc/paperpull/group >/run/paperpull/group \
 && ! id pp \
 && id root && getent group video

# The packages above leave nine setuid programs and three setgid ones, su,
# mount and passwd among them, and nothing here needs any, since the
# entrypoint runs as root and hands everything to pp itself. Without their
# bits, nothing pp runs can become another user through them, even where
# no-new-privileges is off for Chrome's setuid sandbox, whose helper in the
# browser volume is then the only setuid program in the container.
RUN find / -xdev -type f -perm /6000 -exec chmod ug-s {} + \
 && test -z "$(find / -xdev -type f -perm /6000)"

COPY VERSION LICENSE LICENSE-MIT NOTICE.md TRADEMARK.md TERMS.md paperpull.py /opt/paperpull/
COPY core /opt/paperpull/core
# The apps as the packaged desktop build keeps them, templates the panel
# makes each provider's folder from, run by this one Python with no
# environment of their own (gui/app.py, _is_packaged).
COPY apps /opt/paperpull/templates/apps
COPY gui /opt/paperpull/gui
# The scripts the panel runs from tools/ beside its own folder, for the
# Status tab, both spreadsheets and the sample. The panel never takes them
# from the data folder here, which anybody who may write to the share can fill.
COPY tools/status.py tools/export_purchases.py tools/export_transactions.py \
     tools/make_sample.py /opt/paperpull/tools/
COPY tools/add_account.py /opt/paperpull/tools/add_account.py
# Export history and Import history, so a desktop's history comes across (#67).
COPY tools/migrate.py /opt/paperpull/tools/migrate.py
COPY packaging/paperpull.ico /opt/paperpull/packaging/paperpull.ico
COPY server/entrypoint.sh server/chrome.sh server/start.sh server/selftest.py \
     server/reset_password.py /opt/paperpull/server/
COPY server/plugins /opt/paperpull/server/plugins
# Built with the setuptools from the lock, not one fetched for the build.
RUN pip install --no-cache-dir --no-deps --no-build-isolation /opt/paperpull/core \
 && chmod 755 /opt/paperpull/server/entrypoint.sh /opt/paperpull/server/chrome.sh \
              /opt/paperpull/server/start.sh

ENV DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAPERPULL_SERVER=1 \
    PAPERPULL_CONFIG=/config \
    PAPERPULL_PROFILES=/profiles \
    PAPERPULL_PLUGINS=/opt/paperpull/server/plugins \
    XDG_CONFIG_HOME=/config \
    APPS_ROOT=/data

# The panel, behind its password, with the browser screen on the same port.
EXPOSE 8765
VOLUME ["/data", "/profiles", "/config", "/browser"]
ENTRYPOINT ["/opt/paperpull/server/entrypoint.sh"]

# What the image is. The source is what links a published image to this
# repository on GitHub's registry. server/build.py adds the version.
LABEL org.opencontainers.image.title="PaperPull Server" \
      org.opencontainers.image.description="PaperPull on an always-on machine at home, used from a browser on the home network." \
      org.opencontainers.image.source="https://github.com/rheeloaded/paperpull" \
      org.opencontainers.image.vendor="TNE Enterprises LLC" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
