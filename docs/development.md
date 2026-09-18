# Development

## Python development

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run locally:

```bash
python app.py
```

Open `http://127.0.0.1:8080`.

## Tests

Unit tests mock Docker and exercise normalization, CPU calculation, port parsing, Compose grouping, host resource shape, and failure handling:

```bash
python -m unittest discover -s tests -v
```

A live Docker Engine is not required for the unit suite.

## Docker build

```bash
docker build -t docker-desk .
```

## Docker Compose

The checked-in `docker-compose.yml` is intentionally simple:

```bash
docker compose up --build
```

The only deployment setting most users need to change is the host port:

```yaml
ports:
  - "9876:8080"
```

Change `9876`; keep `8080` unchanged.

For background operation:

```bash
docker compose up --build -d
docker compose logs -f docker-desk
```

## Docker socket permissions

Docker Desk expects the host Linux Docker socket at `/var/run/docker.sock` and the Compose deployment mounts it at the same path inside the container.

Inspect the host socket first:

```bash
ls -l /var/run/docker.sock
stat -c 'owner=%u group=%g mode=%a' /var/run/docker.sock
```

The container image runs Gunicorn as the unprivileged `dockerdesk` user. At startup, `docker-entrypoint.py` runs briefly as root to read the socket's numeric GID, adds that GID as a supplementary group, drops privileges to `dockerdesk`, and then starts Gunicorn. This handles hosts where the Docker group has a different numeric GID without hard-coding that value into Compose.

Verify the running container:

```bash
docker compose logs docker-desk
docker compose exec docker-desk id
docker compose exec docker-desk stat -c 'gid=%g mode=%a' /var/run/docker.sock
```

A typical working socket has group-readable/writeable mode such as `0660`. If the socket is `0600` and owned by a different user, Docker Desk cannot gain access merely by adding a supplementary group. Correct the host Docker daemon/socket permissions rather than disabling permissions or running the application as root.

The socket mount itself is required:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

Do not assume `:ro` makes Docker Engine API access read-only. The Docker socket remains a highly privileged host interface. Docker Desk's read-only guarantee is enforced by its application/API surface.

## Refresh

The first page load is a cheap inspect: names, status, health, ports, projects, and images. Docker stats are collected only when Refresh is clicked. That click calls `GET /api/snapshot` once (one Docker client, one-shot stats for running containers) and replaces system, containers, projects, images, and any open container detail. There are no JavaScript timers and no background server worker.

## Debugging

Use the application logs for Docker SDK errors. The browser receives controlled error states rather than Python tracebacks.

Health check:

```bash
curl -fsS http://127.0.0.1:8080/health
```

API checks:

```bash
curl -s http://127.0.0.1:8080/api/snapshot
curl -s http://127.0.0.1:8080/api/system
curl -s http://127.0.0.1:8080/api/containers
curl -s http://127.0.0.1:8080/api/images
```

## Adding Docker data

Keep Docker access in `app.py` and prefer SDK inspection methods. Normalize only the fields the dashboard actually needs. Do not introduce subprocess calls, a database, a Docker management layer, or frontend framework for small additions.
