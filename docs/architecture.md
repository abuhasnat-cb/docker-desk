# Architecture

Docker Desk remains a single lightweight Python application:

```text
                    Linux Host
                         │
                  Docker Engine
                         │
             /var/run/docker.sock
                         │
                         ▼
              ┌───────────────────┐
              │   Docker Desk     │
              │ Flask + Jinja     │
              │ Docker SDK        │
              │ Vanilla JS        │
              └─────────┬─────────┘
                        │
                        ▼
                     Browser
```

## Runtime model

`app.py` owns the Flask routes, host resource readers, Docker SDK calls, and small data-normalization helpers. Jinja renders the initial dashboard. Vanilla JavaScript polls read-only JSON endpoints and updates the DOM without full-page reloads.

The Docker container uses Gunicorn on internal port `8080`. Compose maps the selected host port to that stable internal port. A startup entrypoint briefly runs as root only to discover `/var/run/docker.sock`'s numeric GID, adds it as a supplementary group, drops to the unprivileged `dockerdesk` user, and then execs Gunicorn.

There is no separate frontend application, build system, database, cache, queue, background worker, or Docker management service.

## Docker as source of truth

Container/image/system state comes from the Docker Engine through the Docker SDK. Docker Desk does not execute Docker CLI commands or parse CLI output.

Host RAM and disk information comes from Linux/Python APIs (`/proc/meminfo` and `statvfs`). CPU information uses the Python load-average and CPU-count APIs. This avoids a collection of shell commands and keeps the utility dependency-light.

## Resource statistics

For running containers, Docker Desk requests one non-streaming Docker stats sample and calculates CPU percentage from the current and previous cumulative CPU/system-CPU counters. Memory percentage is derived from usage divided by the reported limit after Docker's cache value is removed when available. Network, block I/O, and PIDs are normalized independently so missing fields do not break other containers.

## Idle heuristic

Docker does not define a universal `idle` state. Docker Desk only labels a running container idle after multiple retained samples meet low CPU and low network-activity thresholds. The heuristic is configurable through environment variables and exists only in process memory. It is intentionally not persisted or presented as Docker state.

## Docker socket and security

The container needs the host Docker socket because that is the local Docker Engine API endpoint:

```text
/var/run/docker.sock
```

A `:ro` Unix-socket mount is not an authorization mechanism for the Docker API. Socket access is still highly privileged and can normally be used to control the Docker host. Docker Desk therefore enforces a read-only application/API surface, but operators should treat socket access as privileged and should not expose this unauthenticated dashboard to untrusted networks.

The image runs the application as an unprivileged `dockerdesk` user. Compose adds the host socket's numeric GID as a supplementary container group (`group_add`), so the application does not need root. The configured GID must match `stat -c '%g' /var/run/docker.sock` on the host.

## Read-only boundary

Only Docker inspection/list operations are used. There are no application routes or UI controls for starting, stopping, restarting, removing, deleting, executing into, pruning, pulling, or building Docker resources.
