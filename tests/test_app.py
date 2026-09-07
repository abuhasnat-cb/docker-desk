import unittest
from unittest.mock import patch

from app import app, calculate_cpu_percent, compose_projects, host_resources, normalize_stats


class FakeImage:
    def __init__(self, image_id="sha256:image-one", tags=None, size=1024):
        self.id = image_id
        self.tags = tags or ["example:latest"]
        self.attrs = {"RepoTags": self.tags, "Created": "2026-01-01T00:00:00Z", "Size": size}


class FakeContainer:
    def __init__(self, name, status="running", project=None, service=None):
        self.id = f"sha256-{name}-identifier"
        self.name = name
        self.status = status
        self.image = FakeImage()
        labels = {}
        if project: labels["com.docker.compose.project"] = project
        if service: labels["com.docker.compose.service"] = service
        self.attrs = {"Config": {"Image": "example:latest", "Labels": labels},
                      "State": {"Status": status, "StartedAt": "2026-09-07T05:00:00Z"},
                      "RestartCount": 0, "Created": "2026-01-01T00:00:00Z",
                      "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]}}}


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

    def test_health_does_not_require_docker(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")

    def test_api_system_returns_controlled_error(self):
        from docker.errors import DockerException
        with patch("app.docker_client", side_effect=DockerException("missing")):
            response = self.client.get("/api/system")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["connected"])

    def test_compose_grouping_and_ports(self):
        from app import _container_payload
        containers = [_container_payload(FakeContainer("web", project="demo", service="web")),
                      _container_payload(FakeContainer("db", status="exited", project="demo", service="db"))]
        projects = compose_projects(containers)
        self.assertEqual(projects[0]["name"], "demo")
        self.assertEqual(projects[0]["running"], 1)
        self.assertEqual(projects[0]["total"], 2)
        self.assertEqual(containers[0]["port_mappings"][0]["published"], "8000")

    def test_cpu_calculation(self):
        stats = {"cpu_stats": {"cpu_usage": {"total_usage": 150}, "system_cpu_usage": 2000, "online_cpus": 2},
                 "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000}}
        self.assertEqual(calculate_cpu_percent(stats), 10.0)
        self.assertIsNone(calculate_cpu_percent({}))

    def test_memory_zero_limit_is_safe(self):
        normalized = normalize_stats({"memory_stats": {"usage": 100, "limit": 0}, "networks": {}, "pids_stats": {}})
        self.assertIsNone(normalized["memory_usage"])
        self.assertIsNone(normalized["memory_percent"])

    def test_stats_normalization(self):
        normalized = normalize_stats({
            "cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 2000, "online_cpus": 1},
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1100},
            "memory_stats": {"usage": 300, "limit": 1000, "stats": {"cache": 100}},
            "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20}},
            "blkio_stats": {"io_service_bytes_recursive": [{"op": "Read", "value": 30}, {"op": "Write", "value": 40}]},
            "pids_stats": {"current": 4},
        })
        self.assertEqual(normalized["cpu_percent"], 9.09)
        self.assertEqual(normalized["memory_usage"], 200)
        self.assertEqual(normalized["network_rx"], 10)
        self.assertEqual(normalized["block_write"], 40)
        self.assertEqual(normalized["pids"], 4)

    def test_host_resources_has_expected_shape(self):
        host = host_resources()
        self.assertIn("memory", host)
        self.assertIn("disk", host)
        self.assertIn("cpu", host)
        self.assertGreaterEqual(host["cpu"]["cores"], 1)


if __name__ == "__main__":
    unittest.main()
