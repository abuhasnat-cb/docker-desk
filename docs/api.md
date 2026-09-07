# API

All endpoints are normal Flask routes and return JSON except `/`, which renders the Jinja dashboard.

## `GET /`

Main dashboard.

## `GET /health`

Application health only. Docker availability is intentionally separate.

Example:

```json
{"status":"ok"}
```

## `GET /api/system`

Returns Docker and host resource information.

Example shape:

```json
{
  "connected": true,
  "docker_version": "28.x",
  "api_version": "1.x",
  "hostname": "linux-host",
  "containers": 7,
  "running": 5,
  "paused": 0,
  "stopped": 2,
  "images": 18,
  "host": {
    "memory": {"used": 4000000000, "total": 8000000000, "available": 4000000000, "percent": 50.0},
    "disk": {"used": 10000000000, "total": 20000000000, "available": 10000000000, "percent": 50.0},
    "cpu": {"load_1m": 1.2, "load_percent_of_cores": 30.0, "cores": 4}
  }
}
```

If Docker cannot be reached, the endpoint returns HTTP `503` with `connected: false` and a controlled error message.

## `GET /api/containers`

Returns all containers plus Compose project grouping. Each container includes status, uptime, health, restart count, raw Docker port bindings, normalized port mappings, and current stats where available.

Resource fields include `cpu_percent`, `memory_usage`, `memory_limit`, `memory_percent`, `network_rx`, `network_tx`, `block_read`, `block_write`, `pids`, and the derived `idle` field.

Example shape:

```json
{
  "containers": [
    {
      "id": "sha256:...",
      "name": "shop-api",
      "status": "running",
      "compose_project": "shop",
      "compose_service": "api",
      "port_mappings": [
        {"host_ip":"0.0.0.0","published":"8000","container":"8000/tcp"}
      ],
      "stats": {"available":true,"cpu_percent":0.8,"memory_usage":184000000,"memory_limit":1000000000,"memory_percent":18.4,"network_rx":12000000,"network_tx":8000000,"block_read":0,"block_write":0,"pids":5,"idle":false}
    }
  ],
  "projects": []
}
```

## `GET /api/containers/<id>`

Returns one container using the same normalized structure as an item in `/api/containers`. Returns `404` if the container no longer exists and `503` when Docker is unavailable.

## `GET /api/containers/<id>/stats`

Returns the normalized current stats for one container. Stopped containers return `available: false` rather than fabricated values.

## `GET /api/images`

Returns image IDs, tags, creation time, size, and the number of current containers referencing each image.

## Read-only behavior

These endpoints do not expose Docker mutation operations. No route starts, stops, restarts, removes, deletes, executes, prunes, pulls, or builds Docker resources.
