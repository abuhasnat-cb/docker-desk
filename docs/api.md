# API

Docker Desk exposes a small internal JSON API. All endpoints are read-only.

## `GET /`

Returns the server-rendered dashboard.

## `GET /api/system`

Returns Docker Engine summary data.

Example:

```json
{
  "connected": true,
  "docker_version": "29.x",
  "api_version": "1.xx",
  "hostname": "developer-machine",
  "containers": 7,
  "running": 5,
  "paused": 0,
  "stopped": 2,
  "images": 18
}
```

When Docker is unavailable, the endpoint returns HTTP 503 with:

```json
{
  "connected": false,
  "error": "Unable to connect to Docker Engine."
}
```

## `GET /api/containers`

Returns all containers and Compose project groupings.

Example shape:

```json
{
  "containers": [
    {
      "id": "...",
      "short_id": "...",
      "name": "shop-api",
      "image": "shop-api:dev",
      "image_id": "sha256:...",
      "status": "running",
      "state": "running",
      "health": null,
      "restart_count": 0,
      "created": "...",
      "ports": {},
      "labels": {},
      "compose_project": "shop",
      "compose_service": "api"
    }
  ],
  "projects": []
}
```

## `GET /api/images`

Returns Docker images and the number of current containers referencing each image.

Example shape:

```json
{
  "images": [
    {
      "id": "sha256:...",
      "short_id": "...",
      "tags": ["postgres:16"],
      "created": "...",
      "size": 123456789,
      "container_count": 1
    }
  ]
}
```

All data is derived from the Docker SDK. There are no mutation endpoints in V0.1.
