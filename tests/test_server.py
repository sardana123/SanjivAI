import json
import threading
import unittest
import urllib.error
import urllib.request

from sanjeevani.app import build_companion
from sanjeevani.config import Settings
from sanjeevani.server import create_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings(db_path=":memory:", port=0, api_token="s3cret")
        cls.c = build_companion(cls.settings)
        cls.srv = create_server(cls.c, cls.settings)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, method, path, body=None, token="s3cret"):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_health_is_public_and_api_needs_token(self):
        self.assertEqual(self.call("GET", "/api/health", token="")[0], 200)
        self.assertEqual(self.call("GET", "/api/patients", token="wrong")[0], 401)

    def test_ui_served(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"Sanjeevani", r.read())

    def test_full_flow(self):
        st, p = self.call("POST", "/api/patients", {"name": "Sita", "caregiver_name": "Ravi"})
        self.assertEqual(st, 201)
        pid = p["id"]
        st, m = self.call("POST", f"/api/patients/{pid}/medications", {"name": "Zinc", "times": ["00:00", "23:59"]})
        self.assertEqual(st, 201)
        st, t = self.call("GET", f"/api/patients/{pid}/today")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(t["doses"]), 1)
        st, r = self.call("POST", f"/api/patients/{pid}/talk", {"text": "what's next"})
        self.assertEqual((st, r["intent"]), (200, "next"))
        st, ins = self.call("GET", f"/api/patients/{pid}/insights?days=7")
        self.assertEqual(st, 200)
        self.assertEqual(len(ins["daily"]), 7)
        self.assertEqual(self.call("DELETE", f"/api/medications/{m['id']}")[0], 200)

    def test_errors_are_clean(self):
        self.assertEqual(self.call("POST", "/api/patients", {"name": ""})[0], 400)
        self.assertEqual(self.call("POST", "/api/patients", {})[0], 400)
        self.assertEqual(self.call("GET", "/api/patients/9999/today")[0], 404)
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        pid = self.call("POST", "/api/patients", {"name": "Err"})[1]["id"]
        st, body = self.call("POST", f"/api/patients/{pid}/medications", {"name": "X", "times": ["99:99"]})
        self.assertEqual(st, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
