from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import docker
from docker.errors import DockerException
from flask import Flask, jsonify, render_template

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("docker-desk")


def docker_client():
    """Create a Docker SDK client using the local/default Docker environment."""
    client = docker.from_env(timeout=3)
    client.ping()
    return client


def _iso_or_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _short_id(identifier: str | None) -> str | None:
    return identifier[:12] if identifier else None


def _container_status(container: Any) -> str:
    return container.status or container.attrs.get("State", {}).get("Status", "unknown")


def _container_payload(container: Any) -> dict[str, Any]:
    attrs = container.attrs or {}
    config = attrs.get("Config", {})
    state = attrs.get("State", {})
    labels = config.get("Labels") or attrs.get("Config", {}).get("Labels") or {}
    image = container.image
    image_id = getattr(image, "id", None) or attrs.get("Image")

    return {
        "id": container.id,
        "short_id": _short_id(container.id),
        "name": container.name,
        "image": config.get("Image") or getattr(image, "tags", [None])[0] or image_id,
        "image_id": image_id,
        "status": _container_status(container),
        "state": state.get("Status"),
        "health": (state.get("Health") or {}).get("Status"),
        "restart_count": attrs.get("RestartCount", 0),
        "created": _iso_or_value(attrs.get("Created")),
        "ports": attrs.get("NetworkSettings", {}).get("Ports") or {},
        "labels": labels,
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
    }


def get_containers() -> list[dict[str, Any]]:
    client = docker_client()
    try:
        containers = client.containers.list(all=True)
        return [_container_payload(container) for container in containers]
    finally:
        client.close()


def get_images(containers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    client = docker_client()
    try:
        images = client.images.list(all=True)
        if containers is None:
            containers = get_containers()

        references: defaultdict[str, int] = defaultdict(int)
        for container in containers:
            image_id = container.get("image_id")
            if image_id:
                references[image_id] += 1

        payload = []
        for image in images:
            attrs = image.attrs or {}
            image_id = image.id
            payload.append(
                {
                    "id": image_id,
                    "short_id": _short_id(image_id),
                    "tags": attrs.get("RepoTags") or [],
                    "created": _iso_or_value(attrs.get("Created")),
                    "size": attrs.get("Size", 0),
                    "container_count": references.get(image_id, 0),
                }
            )
        return payload
    finally:
        client.close()


def get_system(containers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    client = docker_client()
    try:
        info = client.info()
        version = client.version()
        if containers is None:
            containers = get_containers()
        return {
            "connected": True,
            "docker_version": version.get("Version"),
            "api_version": version.get("ApiVersion"),
            "hostname": info.get("Name"),
            "containers": info.get("Containers", len(containers)),
            "running": info.get("ContainersRunning", sum(c["status"] == "running" for c in containers)),
            "paused": info.get("ContainersPaused", sum(c["status"] == "paused" for c in containers)),
            "stopped": info.get("ContainersStopped", sum(c["status"] == "exited" for c in containers)),
            "images": info.get("Images"),
        }
    finally:
        client.close()


def compose_projects(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projects: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for container in containers:
        project = container.get("compose_project")
        if project:
            projects[project].append(container)

    grouped = []
    for name in sorted(projects):
        members = sorted(projects[name], key=lambda item: item["name"])
        grouped.append(
            {
                "name": name,
                "total": len(members),
                "running": sum(item["status"] == "running" for item in members),
                "containers": members,
            }
        )
    return grouped


def dashboard_snapshot() -> dict[str, Any]:
    """Collect the read-only data needed by the dashboard in one pass."""
    try:
        containers = get_containers()
        system = get_system(containers)
        images = get_images(containers)
        return {
            "connected": True,
            "system": system,
            "containers": containers,
            "images": images,
            "projects": compose_projects(containers),
            "error": None,
        }
    except DockerException as exc:
        logger.warning("Docker Engine unavailable: %s", exc)
        return {
            "connected": False,
            "system": None,
            "containers": [],
            "images": [],
            "projects": [],
            "error": "Unable to connect to Docker Engine.",
        }


@app.get("/")
def dashboard():
    return render_template("dashboard.html", **dashboard_snapshot())


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
        containers = get_containers()
        return jsonify({"containers": containers, "projects": compose_projects(containers)})
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/containers: %s", exc)
        return jsonify({"containers": [], "projects": [], "error": "Unable to connect to Docker Engine."}), 503


@app.get("/api/images")
def api_images():
    try:
        containers = get_containers()
        return jsonify({"images": get_images(containers)})
    except DockerException as exc:
        logger.warning("Docker Engine unavailable for /api/images: %s", exc)
        return jsonify({"images": [], "error": "Unable to connect to Docker Engine."}), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
