# Docker Desk

Docker Desk is a small, read-only Linux Docker monitoring dashboard. It puts host resources, Docker status, Compose projects, container resource usage, ports, and images on one dense screen so a developer can glance at the current Docker situation without running several CLI commands.

## V0.3 + V0.4

- Live host RAM, disk, CPU/load, and core information
- Docker Engine version and container/image counts
- Live container CPU, memory, network I/O, block I/O, and PIDs where available
- Explicit host → container port mappings, including TCP/UDP and IPv4/IPv6 bindings returned by Docker
- Compose project grouping and project resource summaries
- Container detail panel with uptime, health, ports, restart count, and resources
- Lightweight search and sorting
- Derived idle indicator based on sustained low CPU and network activity, never from a single sample
- Graceful Docker/socket/stat failures
- `/health` application health endpoint
- Production Gunicorn server
- Docker healthcheck
- One-command Docker Compose deployment
- Fixed internal port `8080`; configurable host port in one line of `docker-compose.yml`

Docker Desk remains inspection-only. It does not start, stop, restart, remove, delete, exec, prune, pull, or build Docker resources.

## Requirements

For Docker deployment:

- Linux host
- Docker Engine
- Docker Compose v2 (`docker compose`)
- Access to `/var/run/docker.sock`

For local Python development:

- Python 3.8+
- Local Docker Engine
- A user that can access the Docker socket

## One-command deployment

The default Compose configuration exposes Docker Desk on host port **9876** and keeps the application inside the container on port **8080**:

```bash
docker compose up --build
```

Open:

```text
http://localhost:9876
```

### Change the host port

Edit exactly one value in `docker-compose.yml`:

```yaml
ports:
  - "9876:8080"
```

Change `9876` to any free host port. Do not change `8080`; that is Docker Desk's internal application port.

For detached operation:

```bash
docker compose up --build -d
```

Stop it with:

```bash
docker compose down
```

View logs with:

```bash
docker compose logs -f docker-desk
```

## Docker socket and security

Docker Desk reads the host Docker Engine through the Linux Unix socket `/var/run/docker.sock`. The Compose deployment mounts that exact host socket into the container:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

The application uses the Docker SDK against the explicit Unix socket `unix:///var/run/docker.sock`. No Docker CLI subprocess is used.

### Why socket permissions matter

A Unix-socket `:ro` bind mount does **not** make Docker API operations read-only. Docker Engine authorization is still controlled by access to the socket/daemon. Anyone who can access the Docker socket should be treated as having highly privileged Docker Engine access. Docker Desk itself exposes only read-only inspection routes and does not implement container/image mutation operations.

The Gunicorn application runs as the unprivileged `dockerdesk` user. Docker Compose grants that user access to the host socket by adding the socket's **numeric GID** as a supplementary container group via `group_add`. The default in this repository is `984`, matching the target Linux host; if `stat -c '%g' /var/run/docker.sock` reports another GID, set `DOCKER_SOCKET_GID` (for example, `DOCKER_SOCKET_GID=998 docker compose up --build -d`). The application never needs to run as root.

This requires the normal Docker socket to be accessible through its owner/group mode bits. A host socket with mode `0600` and an owner other than the Docker Desk runtime user cannot be made accessible by this mechanism without changing host/daemon permissions; Docker Desk will start but report Docker as unavailable.

Check the host socket before starting:

```bash
ls -l /var/run/docker.sock
stat -c 'owner=%u group=%g mode=%a' /var/run/docker.sock
```

For a typical Linux Docker installation, the output resembles a socket owned by `root` and a host Docker group with mode `660`. The **numeric GID** is what matters inside the container; the group name on the host does not need to exist in the image.

Do not use `--privileged`, do not chmod the socket to `666`, and do not run the application as root merely to bypass a socket permission problem.


## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:8080`.

The Python development server remains localhost-only. Production Docker deployment uses Gunicorn.

## Idle heuristic

Docker does not provide a universal semantic `idle` state. Docker Desk derives a temporary indicator only after `DOCKER_DESK_IDLE_SAMPLES` consecutive running-container samples (default 3). A container is considered idle only when every retained sample is at or below `DOCKER_DESK_IDLE_CPU_PERCENT` (default 1%) and each interval's combined network RX/TX increase is at or below `DOCKER_DESK_IDLE_NET_BYTES` (default 4096 bytes).

These values can be changed through environment variables. Idle state is held only in process memory; there is no database and no persistence. `warming up` means there are not enough samples yet.

## API

- `GET /` — Jinja dashboard
- `GET /health` — application health; does not require Docker
- `GET /api/system` — Docker plus host resource information
- `GET /api/containers` — containers, resources, ports, and Compose grouping
- `GET /api/containers/<id>` — one container's details and current stats
- `GET /api/containers/<id>/stats` — one container's normalized stats
- `GET /api/images` — image inventory and container references

See `docs/api.md` for response examples.

## Troubleshooting

### Docker unavailable

Check:

```bash
docker info
test -S /var/run/docker.sock && echo socket-present
```

If Docker Desk is containerized, verify the socket is mounted and inspect:

```bash
docker compose logs -f docker-desk
```

### Permission denied on `/var/run/docker.sock`

First inspect the actual runtime error and socket metadata:

```bash
docker compose logs docker-desk
ls -l /var/run/docker.sock
stat -c 'owner=%u group=%g mode=%a' /var/run/docker.sock
```

At startup Docker Desk logs the numeric socket GID that it discovered. The entrypoint adds that GID as a supplementary group before dropping to the unprivileged `dockerdesk` user. Confirm the running process is not root:

```bash
docker compose exec docker-desk id
docker compose exec docker-desk stat -c 'gid=%g mode=%a' /var/run/docker.sock
```

If the socket is `0600` and owned by a different user, the supplementary-group approach cannot grant access. Fix the host Docker daemon/socket configuration instead; do not use `chmod 666`, `--privileged`, or run the dashboard as root.

The Compose file intentionally does not hard-code a Docker socket GID because Linux distributions and Docker installations can use different numeric GIDs.

### Container statistics are unavailable

Stopped containers have no current resource sample. Some Docker/Engine configurations can also omit block I/O or PID information. Docker Desk renders unavailable values as `—` rather than failing the whole dashboard.

## Testing

Unit tests use mocks and do not require a live Docker Engine:

```bash
python -m unittest discover -s tests -v
```

A real Docker Engine integration check is best performed on the target Linux host:

```bash
docker build -t docker-desk .
docker compose up --build
```

## Project structure

```text
docker-desk/
├── app.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── templates/
│   └── dashboard.html
├── static/
│   ├── style.css
│   └── app.js
├── tests/
│   └── test_app.py
└── docs/
    ├── architecture.md
    ├── api.md
    └── development.md
```
