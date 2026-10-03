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
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# The virtual screen, its window manager, the screen sharing server and the
# web page that shows it, the fonts receipts are printed in, and gpg for
# checking Google's signing key.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tzdata procps \
      xvfb fluxbox x11vnc novnc websockify \
      fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

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

COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The user everything runs as. Its ids follow PUID and PGID at start, so the
# files it writes into a shared folder belong to the person's own NAS user.
RUN useradd --create-home --uid 1000 pp \
 && mkdir -p /data /profiles /config /browser \
 && chown pp:pp /data /profiles /config /browser

COPY VERSION LICENSE LICENSE-MIT NOTICE.md TRADEMARK.md paperpull.py /opt/paperpull/
COPY core /opt/paperpull/core
COPY apps /opt/paperpull/apps
COPY gui /opt/paperpull/gui
COPY packaging/paperpull.ico /opt/paperpull/packaging/paperpull.ico
COPY server/entrypoint.sh server/chrome.sh server/start.sh server/selftest.py /opt/paperpull/server/
RUN pip install --no-cache-dir --no-deps /opt/paperpull/core \
 && chmod 755 /opt/paperpull/server/entrypoint.sh /opt/paperpull/server/chrome.sh \
              /opt/paperpull/server/start.sh

ENV DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAPERPULL_SERVER=1 \
    APPS_ROOT=/data

VOLUME ["/data", "/profiles", "/config", "/browser"]
ENTRYPOINT ["/opt/paperpull/server/entrypoint.sh"]
