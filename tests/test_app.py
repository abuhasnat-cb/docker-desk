import unittest
from unittest.mock import patch

from app import app


class FakeImage:
    def __init__(self, image_id, tags, size):
        self.id = image_id
        self.tags = tags
        self.attrs = {"RepoTags": tags, "Created": "2026-01-01T00:00:00Z", "Size": size}


class FakeContainer:
    def __init__(self, name, image, status, project=None, service=None):
        self.id = f"sha256-{name}-identifier"
        self.name = name
        self.status = status
        self.image = image
        labels = {}
        if project:
            labels["com.docker.compose.project"] = project
        if service:
            labels["com.docker.compose.service"] = service
        self.attrs = {
            "Config": {"Image": image.tags[0], "Labels": labels},
            "State": {"Status": status},
            "RestartCount": 0,
            "Created": "2026-01-01T00:00:00Z",
            "NetworkSettings": {"Ports": {}},
        }


class FakeDockerClient:
    def __init__(self):
        image = FakeImage("sha256:image-one", ["example:latest"], 1024 * 1024)
        self._images = [image]
        self._containers = [FakeContainer("example", image, "running", "demo", "web")]

    def ping(self):
        return True

    def info(self):
        return {
            "Name": "test-host",
            "Containers": 1,
            "ContainersRunning": 1,
            "ContainersPaused": 0,
            "ContainersStopped": 0,
            "Images": 1,
        }

    def version(self):
        return {"Version": "test", "ApiVersion": "1.0"}

    class containers:
        @staticmethod
        def list(all=False):
            return []

    class images:
        @staticmethod
        def list(all=False):
            return []

    def close(self):
        return None


class DockerDeskTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_dashboard_handles_missing_docker(self):
        from docker.errors import DockerException
        with patch("app.docker_client", side_effect=DockerException("missing")):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Docker unavailable", response.data)

    def test_api_system_returns_controlled_error(self):
        from docker.errors import DockerException
        with patch("app.docker_client", side_effect=DockerException("missing")):
            response = self.client.get("/api/system")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["connected"])

    def test_compose_grouping(self):
        from app import compose_projects
        image = FakeImage("sha256:image-one", ["example:latest"], 1024)
        containers = [
            app._container_payload(FakeContainer("web", image, "running", "demo", "web")),
            app._container_payload(FakeContainer("db", image, "exited", "demo", "db")),
        ]
        projects = compose_projects(containers)
        self.assertEqual(projects[0]["name"], "demo")
        self.assertEqual(projects[0]["running"], 1)
        self.assertEqual(projects[0]["total"], 2)


if __name__ == "__main__":
    unittest.main()
