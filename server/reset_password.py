"""Forget PaperPull Server's password, so a new one can be chosen.

    docker exec paperpull python /opt/paperpull/server/reset_password.py

Everyone signed in is signed out at once. The next visit to the panel asks
for a new password, with a new setup code the container prints in its log
then (docker logs paperpull). Nothing else in the settings is touched.

It runs as the user pp, as the panel does, since `docker exec` starts as
root and a settings file written by root is one the panel could not read.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/opt/paperpull/gui")


def as_pp() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.execvp("setpriv", ["setpriv", "--reuid=pp", "--regid=pp", "--init-groups",
                              "env", "HOME=/home/pp", "USER=pp", sys.executable,
                              os.path.abspath(__file__)])


def main() -> int:
    as_pp()
    import server_mode

    data = server_mode._read()
    if not data.get("password"):
        print("PaperPull Server has no password now. Open the panel to choose one.")
        return 0
    del data["password"]
    server_mode._write(data)
    print("The password is gone, and everyone signed in is signed out. Open the panel\n"
          "to choose a new one. The setup code it asks for is in this container's log\n"
          "once the page is open (docker logs paperpull).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
