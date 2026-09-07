from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound
from flask import Flask, jsonify, render_template

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("docker-desk")

DOCKER_TIMEOUT = float(os.getenv("DOCKER_TIMEOUT", "5"))
IDLE_CPU_PERCENT = float(os.getenv("DOCKER_DESK_IDLE_CPU_PERCENT", "1.0"))
IDLE_NET_BYTES = int(os.getenv("DOCKER_DESK_IDLE_NET_BYTES", "4096"))
IDLE_SAMPLES = max(2, int(os.getenv("DOCKER_DESK_IDLE_SAMPLES", "3")))

# Deliberately in-memory: idle is a transient UI heuristic, not persisted state.
_idle_samples: dict[str, list[tuple[float, int, int]]] = {}


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


def _iso_or_value(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


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


def _update_idle(container_id: str, stats: dict[str, Any]) -> bool | None:
    cpu = stats.get("cpu_percent")
    rx = stats.get("network_rx")
    tx = stats.get("network_tx")
    if cpu is None or rx is None or tx is None:
        _idle_samples.pop(container_id, None)
        return None

    samples = _idle_samples.setdefault(container_id, [])
    samples.append((float(cpu), int(rx), int(tx)))
    if len(samples) > IDLE_SAMPLES:
        del samples[:-IDLE_SAMPLES]
    if len(samples) < IDLE_SAMPLES:
        return None

    cpu_low = all(sample[0] <= IDLE_CPU_PERCENT for sample in samples)
    network_low = all(
        (samples[index][1] - samples[index - 1][1]) + (samples[index][2] - samples[index - 1][2]) <= IDLE_NET_BYTES
        for index in range(1, len(samples))
    )
    return cpu_low and network_low


def get_container_stats(container: Any) -> dict[str, Any]:
    if _container_status(container) != "running":
        return empty_stats()
    try:
        stats = normalize_stats(container.stats(stream=False))
        stats["idle"] = _update_idle(container.id, stats)
        return stats
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


def _container_payload(container: Any, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    attrs = container.attrs or {}
    config = attrs.get("Config", {})
    state = attrs.get("State", {})
    labels = config.get("Labels") or {}
    image = container.image
    tags = getattr(image, "tags", []) or []
    image_id = getattr(image, "id", None) or attrs.get("Image")
    ports = attrs.get("NetworkSettings", {}).get("Ports") or {}
    return {
        "id": container.id, "short_id": _short_id(container.id), "name": container.name,
        "image": config.get("Image") or (tags[0] if tags else image_id), "image_id": image_id,
        "status": _container_status(container), "state": state.get("Status"),
        "health": (state.get("Health") or {}).get("Status"), "restart_count": attrs.get("RestartCount", 0),
        "created": _iso_or_value(attrs.get("Created")), "started_at": _iso_or_value(state.get("StartedAt")),
        "uptime_seconds": _uptime_seconds(state.get("StartedAt")), "ports": ports,
        "port_mappings": _format_ports(ports), "labels": labels,
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "stats": stats or empty_stats(),
    }


def get_containers(include_stats: bool = True) -> list[dict[str, Any]]:
    client = docker_client()
    try:
        payload = []
        for container in client.containers.list(all=True):
            try:
                payload.append(_container_payload(container, get_container_stats(container) if include_stats else empty_stats()))
            except (APIError, DockerException) as exc:
                logger.warning("Skipping container that disappeared: %s", exc)
        return payload
    finally:
        client.close()


def get_container(container_id: str, include_stats: bool = True) -> dict[str, Any]:
    client = docker_client()
    try:
        container = client.containers.get(container_id)
        return _container_payload(container, get_container_stats(container) if include_stats else empty_stats())
    finally:
        client.close()


def get_images(containers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    client = docker_client()
    try:
        images = client.images.list(all=True)
        containers = containers if containers is not None else get_containers(include_stats=False)
        references: defaultdict[str, int] = defaultdict(int)
        for container in containers:
            if container.get("image_id"):
                references[container["image_id"]] += 1
        return [{
            "id": image.id, "short_id": _short_id(image.id), "tags": (image.attrs or {}).get("RepoTags") or [],
            "created": _iso_or_value((image.attrs or {}).get("Created")), "size": (image.attrs or {}).get("Size", 0),
            "container_count": references.get(image.id, 0),
        } for image in images]
    finally:
        client.close()


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


def get_system(containers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    client = docker_client()
    try:
        info = client.info()
        version = client.version()
        containers = containers if containers is not None else get_containers(include_stats=False)
        return {
            "connected": True, "docker_version": version.get("Version"), "api_version": version.get("ApiVersion"),
            "hostname": info.get("Name"), "containers": info.get("Containers", len(containers)),
            "running": info.get("ContainersRunning", sum(c["status"] == "running" for c in containers)),
            "paused": info.get("ContainersPaused", sum(c["status"] == "paused" for c in containers)),
            "stopped": info.get("ContainersStopped", sum(c["status"] in {"exited", "created"} for c in containers)),
            "images": info.get("Images", 0), "host": host_resources(),
        }
    finally:
        client.close()


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


def dashboard_snapshot() -> dict[str, Any]:
    try:
        containers = get_containers(include_stats=True)
        system = get_system(containers)
        return {"connected": True, "system": system, "containers": containers,
                "images": get_images(containers), "projects": compose_projects(containers), "error": None}
    except DockerException as exc:
        logger.warning("Docker Engine unavailable: %s", exc)
        return {"connected": False, "system": None, "containers": [], "images": [], "projects": [],
                "error": "Unable to connect to Docker Engine."}


@app.get("/")
def dashboard():
    return render_template("dashboard.html", **dashboard_snapshot())


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


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
        containers = get_containers(include_stats=True)
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
        containers = get_containers(include_stats=False)
        return jsonify({"images": get_images(containers)})
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/images: %s", exc)
        return jsonify({"images": [], "error": "Unable to connect to Docker Engine."}), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
