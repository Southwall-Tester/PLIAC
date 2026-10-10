"""New SPA entrypoint must not replace existing APIs or legacy pages."""
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from pliac.main import app


class StudentAppTests(unittest.TestCase):
    def test_health_identifies_current_guide_without_claiming_readiness(self):
        with TestClient(app) as client:
            response = client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['specification'], 'build-guide-20261009-v1.6')
        self.assertEqual(response.json()['student_entry'], '/app/')
        self.assertNotIn('ready_for_students', response.json())

    def test_build_missing_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory, patch("pliac.main.ROOT", Path(directory)):
            with TestClient(app) as client:
                self.assertEqual(client.get("/app").status_code, 503)
                self.assertEqual(client.get("/health").status_code, 200)

    def test_nested_routes_assets_and_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory, patch("pliac.main.ROOT", Path(directory)):
            root = Path(directory)
            assets = root / "web/dist/assets"
            assets.mkdir(parents=True)
            (assets.parent / "index.html").write_text("<title>PLIAC</title>", encoding="utf-8")
            (assets / "main.js").write_text("export const ready = true;", encoding="utf-8")
            (root / "secret.txt").write_text("private", encoding="utf-8")
            with TestClient(app) as client:
                response = client.get("/app/courses/example")
                self.assertEqual(response.status_code, 200)
                self.assertIn("PLIAC", response.text)
                self.assertEqual(response.headers["cache-control"], "no-cache")
                self.assertEqual(client.get("/app/assets/main.js").status_code, 200)
                self.assertEqual(client.get("/app/assets/missing.js").status_code, 404)
                self.assertNotIn("private", client.get("/app/assets/%2e%2e/%2e%2e/%2e%2e/secret.txt").text)
                self.assertEqual(client.get("/api/not-a-real-api").status_code, 404)


if __name__ == "__main__":
    unittest.main()
