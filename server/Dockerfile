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

COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The user everything runs as. Its ids follow PUID and PGID at start, so the
# files it writes into a shared folder belong to the person's own NAS user.
RUN useradd --create-home --uid 1000 pp \
 && mkdir -p /data /profiles /config /browser \
 && chown pp:pp /data /profiles /config /browser

COPY VERSION LICENSE LICENSE-MIT NOTICE.md TRADEMARK.md paperpull.py /opt/paperpull/
COPY core /opt/paperpull/core
# The apps as the packaged desktop build keeps them, templates the panel
# makes each provider's folder from, run by this one Python with no
# environment of their own (gui/app.py, _is_packaged).
COPY apps /opt/paperpull/templates/apps
COPY gui /opt/paperpull/gui
COPY tools/add_account.py /opt/paperpull/tools/add_account.py
COPY packaging/paperpull.ico /opt/paperpull/packaging/paperpull.ico
COPY server/entrypoint.sh server/chrome.sh server/start.sh server/selftest.py \
     server/reset_password.py /opt/paperpull/server/
COPY server/plugins /opt/paperpull/server/plugins
RUN pip install --no-cache-dir --no-deps /opt/paperpull/core \
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
