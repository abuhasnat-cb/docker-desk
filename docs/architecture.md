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

`app.py` owns the Flask routes, host resource readers, Docker SDK calls, and small data-normalization helpers. Jinja renders the initial dashboard without container stats. Vanilla JavaScript updates the DOM from `GET /api/snapshot` only when the Refresh button is clicked; there is no background polling.

The Docker container uses Gunicorn on internal port `8080` with one worker. Compose maps the selected host port to that stable internal port, and caps the container at 128MB RAM and 0.25 CPU. Compose `group_add` supplies the host Docker socket GID so the unprivileged `dockerdesk` user can read the socket.

There is no separate frontend application, build system, database, cache, queue, background worker, or Docker management service.

## Docker as source of truth

Container/image/system state comes from the Docker Engine through the Docker SDK. Docker Desk does not execute Docker CLI commands or parse CLI output.

Host RAM and disk information comes from Linux/Python APIs (`/proc/meminfo` and `statvfs`). CPU information uses the Python load-average and CPU-count APIs. This avoids a collection of shell commands and keeps the utility dependency-light.

## Resource statistics

The first page load lists containers, Compose projects, and images without calling Docker stats. Refresh uses a single `/api/snapshot` request on one Docker client. For running containers it requests a one-shot stats sample (`one_shot=True`) so the daemon does not wait ~1s per container. CPU percentage is calculated from the current and previous cumulative CPU counters when the sample includes them; otherwise the UI shows `—`. Memory percentage is derived from usage divided by the reported limit after Docker's cache value is removed when available. Network, block I/O, and PIDs are normalized independently so missing fields do not break other containers.

## Docker socket and security

The container needs the host Docker socket because that is the local Docker Engine API endpoint:

```text
/var/run/docker.sock
```

A `:ro` Unix-socket mount is not an authorization mechanism for the Docker API. Socket access is still highly privileged and can normally be used to control the Docker host. Docker Desk therefore enforces a read-only application/API surface, but operators should treat socket access as privileged and should not expose this unauthenticated dashboard to untrusted networks.

The image runs the application as an unprivileged `dockerdesk` user. Compose adds the host socket's numeric GID as a supplementary container group (`group_add`), so the application does not need root. The configured GID must match `stat -c '%g' /var/run/docker.sock` on the host.

## Read-only boundary

Only Docker inspection/list operations are used. There are no application routes or UI controls for starting, stopping, restarting, removing, deleting, executing into, pruning, pulling, or building Docker resources.
