"""Device authentication tests use private fake peers, never a live account."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from manager import app as module, device_access


class DeviceAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=module.ROOT)
        self.addCleanup(self.temp.cleanup)
        self.app = module.create_app(Path(self.temp.name) / "db", start_dispatcher=False,
                                     network_hosts=["192.168.1.20"],device_pairing_required=True)
        self.local = TestClient(self.app)
        self.remote = TestClient(self.app, base_url="http://192.168.1.20:8765", client=("192.168.1.21", 50000))
        self.addCleanup(self.local.close); self.addCleanup(self.remote.close)
        self.headers = {"X-Novel-Helper": "1"}

    def pair(self):
        code = self.local.post("/api/access/code", json={}, headers=self.headers).json()["code"]
        response = self.remote.post("/api/access/pair", json={"code": code, "name": "测试平板"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return code, response

    def test_unpaired_cannot_read_data_or_spoof_forwarded_loopback(self):
        for path in ("/api/overview", "/api/ai", "/api/projects", "/openapi.json", "/static/app.js"):
            self.assertEqual(self.remote.get(path, headers={"X-Forwarded-For": "127.0.0.1"}).status_code, 401)
        response = self.remote.get("/", follow_redirects=False)
        self.assertEqual(response.headers["location"], "/pair")
        self.assertEqual(self.remote.get("/pair").status_code, 200)

    def test_pair_cookie_single_use_and_local_only_controls(self):
        code, response = self.pair()
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie); self.assertIn("samesite=strict", cookie)
        self.assertEqual(self.remote.get("/api/projects").status_code, 200)
        self.assertFalse(self.remote.get("/api/access").json()["local"])
        self.assertEqual(self.remote.post("/api/access/code", json={}, headers=self.headers).status_code, 403)
        self.assertEqual(self.remote.post("/api/access/pair", json={"code": code}, headers=self.headers).status_code, 401)
        record = self.local.get("/api/access").json()["devices"][0]
        self.assertEqual(self.remote.delete(f"/api/access/devices/{record['id']}", headers=self.headers).status_code, 403)
        self.assertEqual(self.local.delete(f"/api/access/devices/{record['id']}", headers=self.headers).status_code, 200)
        self.assertEqual(self.remote.get("/api/projects").status_code, 401)

    def test_expired_codes_sessions_logout_and_request_guards(self):
        code = self.local.post("/api/access/code", json={}, headers=self.headers).json()["code"]
        self.app.state.device_access.code_expires = time.time() - 1
        self.assertEqual(self.remote.post("/api/access/pair", json={"code": code}, headers=self.headers).status_code, 401)
        self.pair()
        headers = {**self.headers, "Origin": "http://unrelated.invalid"}
        self.assertEqual(self.remote.post("/api/access/logout", json={}, headers=headers).status_code, 403)
        self.assertEqual(self.remote.post("/api/access/logout", json={}).status_code, 403)
        self.assertEqual(self.remote.post("/api/access/logout", json={}, headers=self.headers).status_code, 200)
        self.assertEqual(self.remote.get("/api/projects").status_code, 401)
        self.pair()
        for record in self.app.state.device_access.sessions.values(): record["expires_at"] = time.time() - 1
        self.assertEqual(self.remote.get("/api/projects").status_code, 401)

    def test_rate_limit_and_public_peer_rejection(self):
        for _ in range(10):
            self.assertEqual(self.remote.post("/api/access/pair", json={"code":"00000000"}, headers=self.headers).status_code, 401)
        self.assertEqual(self.remote.post("/api/access/pair", json={"code":"00000000"}, headers=self.headers).status_code, 429)
        with TestClient(self.app, client=("8.8.8.8", 50000)) as public:
            self.assertEqual(public.get("/api/health").status_code, 403)
        self.assertFalse(device_access.private_address("59.66.27.113"))
        self.assertFalse(device_access.private_address("198.18.0.1"))
        self.assertTrue(device_access.private_address("100.102.127.60"))
        self.assertEqual(self.local.get("/api/health", headers={"Host":"evil.invalid"}).status_code, 400)

    def test_only_explicit_interfaces_and_new_instance_revokes_sessions(self):
        self.pair()
        fresh = module.create_app(Path(self.temp.name) / "new-db", start_dispatcher=False, network_hosts=["192.168.1.20"],device_pairing_required=True)
        with TestClient(fresh, base_url="http://192.168.1.20:8765", client=("192.168.1.21", 50000)) as client:
            client.cookies.update(self.remote.cookies)
            self.assertEqual(client.get("/api/projects").status_code, 401)
        with patch.object(device_access.socket, "getaddrinfo", return_value=[(None,None,None,None,(ip,0)) for ip in ["127.0.0.1", "192.168.1.20", "59.66.27.113", "100.102.127.60"]]):
            self.assertEqual(device_access.local_addresses(), ["100.102.127.60", "192.168.1.20"])


if __name__ == "__main__":
    unittest.main()
