from __future__ import annotations

import logging
import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import docker
from docker.errors import APIError, DockerException, NotFound
from flask import Flask, jsonify, render_template

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("docker-desk")

DOCKER_TIMEOUT = float(os.getenv("DOCKER_TIMEOUT", "5"))


def docker_client():
    # The container entrypoint pins DOCKER_HOST to the mounted Unix socket.
    # Keep the same default for local Python development and avoid silently
    # following an unrelated TCP daemon endpoint.
    socket_path = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
    docker_host = os.getenv("DOCKER_HOST") or f"unix://{socket_path}"
    client = docker.DockerClient(base_url=docker_host, timeout=DOCKER_TIMEOUT)
    try:
        client.ping()
    except DockerException:
        client.close()
        raise
    return client


@contextmanager
def docker_session() -> Iterator[Any]:
    client = docker_client()
    try:
        yield client
    finally:
        client.close()


def _iso_or_value(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except (OSError, OverflowError, ValueError, TypeError):
            return None


def _age_text(created: Any, now: datetime | None = None) -> str:
    parsed = _parse_datetime(created)
    if parsed is None:
        return "—"
    current = now or datetime.now(timezone.utc)
    seconds = max(0, int((current - parsed).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    days = seconds // 86400
    if days < 60:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def _short_id(identifier: str | None) -> str | None:
    return identifier[:12] if identifier else None


def _uptime_seconds(started_at: str | None) -> int | None:
    if not started_at or started_at.startswith("0001-01-01"):
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    except (TypeError, ValueError):
        return None


def _container_status(container: Any) -> str:
    return container.status or container.attrs.get("State", {}).get("Status", "unknown")


def empty_stats() -> dict[str, Any]:
    return {
        "available": False, "cpu_percent": None, "memory_usage": None,
        "memory_limit": None, "memory_percent": None, "network_rx": None,
        "network_tx": None, "block_read": None, "block_write": None, "pids": None,
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_cpu_percent(stats: dict[str, Any]) -> float | None:
    cpu = stats.get("cpu_stats") or {}
    previous = stats.get("precpu_stats") or {}
    cpu_delta = _number((cpu.get("cpu_usage") or {}).get("total_usage")) - _number(
        (previous.get("cpu_usage") or {}).get("total_usage")
    )
    system_delta = _number(cpu.get("system_cpu_usage")) - _number(previous.get("system_cpu_usage"))
    if cpu_delta <= 0 or system_delta <= 0:
        return None
    online_cpus = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    return round((cpu_delta / system_delta) * int(online_cpus) * 100.0, 2)


def _memory_values(stats: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    memory = stats.get("memory_stats") or {}
    limit = _number(memory.get("limit"), 0)
    usage = _number(memory.get("usage"), 0)
    cache = _number((memory.get("stats") or {}).get("cache"), 0)
    usage = max(0.0, usage - cache)
    if limit <= 0:
        return None, None, None
    return usage, limit, round((usage / limit) * 100.0, 2)


def _network_values(stats: dict[str, Any]) -> tuple[int, int]:
    rx = tx = 0
    for interface in (stats.get("networks") or {}).values():
        rx += int(_number(interface.get("rx_bytes")))
        tx += int(_number(interface.get("tx_bytes")))
    return rx, tx


def _block_values(stats: dict[str, Any]) -> tuple[int, int]:
    read = write = 0
    entries = (stats.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
    for item in entries:
        value = int(_number(item.get("value")))
        op = str(item.get("op", "")).lower()
        if op == "read":
            read += value
        elif op in {"write", "writ"}:
            write += value
    return read, write


def normalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    usage, limit, memory_percent = _memory_values(stats)
    network_rx, network_tx = _network_values(stats)
    block_read, block_write = _block_values(stats)
    pids = (stats.get("pids_stats") or {}).get("current")
    return {
        "available": True,
        "cpu_percent": calculate_cpu_percent(stats),
        "memory_usage": int(usage) if usage is not None else None,
        "memory_limit": int(limit) if limit is not None else None,
        "memory_percent": memory_percent,
        "network_rx": network_rx,
        "network_tx": network_tx,
        "block_read": block_read,
        "block_write": block_write,
        "pids": int(pids) if pids is not None else None,
    }


def get_container_stats(container: Any) -> dict[str, Any]:
    if _container_status(container) != "running":
        return empty_stats()
    try:
        # one_shot uses the daemon's latest sample instead of waiting ~1s per container.
        return normalize_stats(container.stats(stream=False, one_shot=True))
    except (APIError, DockerException) as exc:
        logger.warning("Unable to read stats for %s: %s", getattr(container, "name", container.id), exc)
        return empty_stats()


def _format_ports(ports: dict[str, Any] | None) -> list[dict[str, Any]]:
    mappings = []
    for container_port, bindings in (ports or {}).items():
        if not bindings:
            mappings.append({"container": container_port, "published": None, "host_ip": None})
            continue
        for binding in bindings:
            mappings.append({
                "container": container_port,
                "published": binding.get("HostPort"),
                "host_ip": binding.get("HostIp") or "0.0.0.0",
            })
    return mappings


def _ports_text(mappings: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for mapping in mappings:
        published = mapping.get("published")
        if not published:
            continue
        port = str(published)
        if port in seen:
            continue
        seen.add(port)
        labels.append(port)
    return ", ".join(labels) if labels else "—"


def _container_payload(container: Any, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    attrs = container.attrs or {}
    config = attrs.get("Config", {})
    state = attrs.get("State", {})
    labels = config.get("Labels") or {}
    image_id = attrs.get("Image")
    ports = attrs.get("NetworkSettings", {}).get("Ports") or {}
    port_mappings = _format_ports(ports)
    return {
        "id": container.id, "short_id": _short_id(container.id), "name": container.name,
        "image": config.get("Image") or image_id, "image_id": image_id,
        "status": _container_status(container), "state": state.get("Status"),
        "health": (state.get("Health") or {}).get("Status"), "restart_count": attrs.get("RestartCount", 0),
        "created": _iso_or_value(attrs.get("Created")), "started_at": _iso_or_value(state.get("StartedAt")),
        "uptime_seconds": _uptime_seconds(state.get("StartedAt")), "ports": ports,
        "port_mappings": port_mappings, "ports_text": _ports_text(port_mappings),
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "stats": stats or empty_stats(),
    }


def _list_containers(client: Any, include_stats: bool) -> list[dict[str, Any]]:
    payload = []
    for container in client.containers.list(all=True):
        try:
            stats = get_container_stats(container) if include_stats else empty_stats()
            payload.append(_container_payload(container, stats))
        except (APIError, DockerException) as exc:
            logger.warning("Skipping container that disappeared: %s", exc)
    return payload


def _image_payload(image: Any, users: list[dict[str, Any]]) -> dict[str, Any]:
    tags = [tag for tag in ((image.attrs or {}).get("RepoTags") or []) if tag and tag != "<none>:<none>"]
    dangling = not tags
    running = sum(1 for container in users if container.get("status") == "running")
    stopped = max(0, len(users) - running)
    if dangling and not users:
        use_text = "dangling"
    elif not users:
        use_text = "unused"
    else:
        parts = []
        if running:
            parts.append(f"{running} running")
        if stopped:
            parts.append(f"{stopped} stopped")
        use_text = " · ".join(parts)
    names = [container.get("name") or container.get("short_id") for container in users]
    names = [name for name in names if name]
    if len(names) > 3:
        used_by_text = ", ".join(names[:3]) + f" +{len(names) - 3}"
    else:
        used_by_text = ", ".join(names) if names else "—"
    created = (image.attrs or {}).get("Created")
    return {
        "id": image.id, "short_id": _short_id(image.id), "tags": tags,
        "created": _iso_or_value(created), "age_text": _age_text(created),
        "size": (image.attrs or {}).get("Size", 0), "dangling": dangling, "in_use": bool(users),
        "container_count": len(users), "use_text": use_text, "used_by_text": used_by_text,
    }


def _list_images(client: Any, containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    users_by_image: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for container in containers:
        if container.get("image_id"):
            users_by_image[container["image_id"]].append(container)
    images = [_image_payload(image, users_by_image.get(image.id, [])) for image in client.images.list()]
    images.sort(key=lambda item: (not item["in_use"], item["dangling"], -(item["size"] or 0)))
    return images


def _system_payload(client: Any) -> dict[str, Any]:
    info = client.info()
    return {
        "connected": True, "docker_version": info.get("ServerVersion"),
        "api_version": info.get("ApiVersion"), "hostname": info.get("Name"),
        "containers": info.get("Containers", 0), "running": info.get("ContainersRunning", 0),
        "paused": info.get("ContainersPaused", 0), "stopped": info.get("ContainersStopped", 0),
        "images": info.get("Images", 0), "host": host_resources(),
    }


def get_containers(include_stats: bool = True) -> list[dict[str, Any]]:
    with docker_session() as client:
        return _list_containers(client, include_stats)


def get_container(container_id: str, include_stats: bool = True) -> dict[str, Any]:
    with docker_session() as client:
        container = client.containers.get(container_id)
        stats = get_container_stats(container) if include_stats else empty_stats()
        return _container_payload(container, stats)


def get_images(containers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    with docker_session() as client:
        if containers is None:
            containers = _list_containers(client, include_stats=False)
        return _list_images(client, containers)


def _read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                parts = value.strip().split()
                if parts:
                    values[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        pass
    return values


def host_resources() -> dict[str, Any]:
    mem = _read_meminfo()
    total = mem.get("MemTotal")
    available = mem.get("MemAvailable")
    used = total - available if total is not None and available is not None else None
    disk = None
    try:
        usage = os.statvfs("/")
        total_disk = usage.f_blocks * usage.f_frsize
        available_disk = usage.f_bavail * usage.f_frsize
        used_disk = total_disk - available_disk
        disk = {"used": used_disk, "total": total_disk, "available": available_disk,
                "percent": round(used_disk / total_disk * 100, 2) if total_disk else None}
    except OSError:
        pass
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    cores = os.cpu_count() or 1
    return {
        "memory": {"used": used, "total": total, "available": available,
                   "percent": round(used / total * 100, 2) if total and used is not None else None},
        "disk": disk,
        "cpu": {"load_1m": round(load, 2) if load is not None else None,
                "load_percent_of_cores": round(load / cores * 100, 2) if load is not None else None,
                "cores": cores},
    }


def get_system() -> dict[str, Any]:
    with docker_session() as client:
        return _system_payload(client)


def _project_resource_summary(containers: list[dict[str, Any]]) -> dict[str, Any]:
    running = [c for c in containers if c["status"] == "running"]
    stats = [c["stats"] for c in running if c["stats"].get("available")]
    return {
        "cpu_percent": round(sum(s["cpu_percent"] or 0 for s in stats), 2) if stats else None,
        "memory_usage": sum(s["memory_usage"] or 0 for s in stats) if stats else None,
        "network_rx": sum(s["network_rx"] or 0 for s in stats) if stats else None,
        "network_tx": sum(s["network_tx"] or 0 for s in stats) if stats else None,
    }


def compose_projects(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projects: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for container in containers:
        if container.get("compose_project"):
            projects[container["compose_project"]].append(container)
    return [{
        "name": name, "total": len(members), "running": sum(c["status"] == "running" for c in members),
        "stopped": sum(c["status"] != "running" for c in members),
        "resources": _project_resource_summary(members), "containers": sorted(members, key=lambda c: c["name"]),
    } for name, members in sorted(projects.items())]


def dashboard_snapshot(include_stats: bool = False) -> dict[str, Any]:
    try:
        with docker_session() as client:
            containers = _list_containers(client, include_stats)
            return {
                "connected": True, "system": _system_payload(client), "containers": containers,
                "images": _list_images(client, containers), "projects": compose_projects(containers),
                "error": None,
            }
    except DockerException as exc:
        logger.warning("Docker Engine unavailable: %s", exc)
        return {"connected": False, "system": None, "containers": [], "images": [], "projects": [],
                "error": "Unable to connect to Docker Engine."}


@app.get("/")
def dashboard():
    return render_template("dashboard.html", **dashboard_snapshot(include_stats=False))


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/snapshot")
def api_snapshot():
    snapshot = dashboard_snapshot(include_stats=True)
    if not snapshot["connected"]:
        return jsonify(snapshot), 503
    return jsonify(snapshot)


@app.get("/api/system")
def api_system():
    try:
        return jsonify(get_system())
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/system: %s", exc)
        return jsonify({"connected": False, "error": "Unable to connect to Docker Engine."}), 503


@app.get("/api/containers")
def api_containers():
    try:
        with docker_session() as client:
            containers = _list_containers(client, include_stats=True)
            return jsonify({"containers": containers, "projects": compose_projects(containers)})
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/containers: %s", exc)
        return jsonify({"containers": [], "projects": [], "error": "Unable to connect to Docker Engine."}), 503


@app.get("/api/containers/<container_id>")
def api_container(container_id: str):
    try:
        return jsonify(get_container(container_id, include_stats=True))
    except NotFound:
        return jsonify({"error": "Container not found."}), 404
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/containers/%s: %s", container_id, exc)
        return jsonify({"error": "Unable to connect to Docker Engine."}), 503


@app.get("/api/containers/<container_id>/stats")
def api_container_stats(container_id: str):
    try:
        return jsonify(get_container(container_id, include_stats=True)["stats"])
    except NotFound:
        return jsonify({"error": "Container not found."}), 404
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for stats %s: %s", container_id, exc)
        return jsonify({"available": False, "error": "Unable to connect to Docker Engine."}), 503


@app.get("/api/images")
def api_images():
    try:
        return jsonify({"images": get_images()})
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/images: %s", exc)
        return jsonify({"images": [], "error": "Unable to connect to Docker Engine."}), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
