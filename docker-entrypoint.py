#!/usr/bin/env python3
"""Start Docker Desk and verify the mounted Docker socket is accessible."""
from __future__ import annotations

import os
import socket
import stat
import sys

SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")


def main() -> None:
    if len(sys.argv) < 2:
        print("docker-entrypoint: no command specified", file=sys.stderr)
        raise SystemExit(2)

    os.environ["DOCKER_HOST"] = f"unix://{SOCKET}"

    try:
        socket_stat = os.stat(SOCKET)
    except FileNotFoundError:
        print(f"docker-entrypoint: Docker socket not found: {SOCKET}", file=sys.stderr)
    except PermissionError as exc:
        print(f"docker-entrypoint: cannot stat Docker socket {SOCKET}: {exc}", file=sys.stderr)
    else:
        if not stat.S_ISSOCK(socket_stat.st_mode):
            print(f"docker-entrypoint: {SOCKET} exists but is not a Unix socket", file=sys.stderr)
        else:
            print(
                f"docker-entrypoint: socket={SOCKET} uid={socket_stat.st_uid} "
                f"gid={socket_stat.st_gid} mode={stat.S_IMODE(socket_stat.st_mode):o}; "
                f"process uid={os.getuid()} gid={os.getgid()} groups={os.getgroups()} "
                f"DOCKER_HOST={os.environ['DOCKER_HOST']}",
                file=sys.stderr,
            )

            # A connect attempt gives a much more useful startup diagnostic than
            # waiting for the first dashboard request. Do not fail startup: Docker
            # may become available after the container starts.
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.settimeout(1.0)
                probe.connect(SOCKET)
                probe.close()
                print("docker-entrypoint: Docker socket is accessible", file=sys.stderr)
            except OSError as exc:
                print(f"docker-entrypoint: Docker socket is not accessible: {exc}", file=sys.stderr)

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
