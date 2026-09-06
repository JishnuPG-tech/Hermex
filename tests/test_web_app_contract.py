import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "official" / "web"


class WebAppContractTests(unittest.TestCase):
    def test_official_dashboard_source_is_pinned_and_buildable(self):
        package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["name"], "web")
        self.assertTrue((ROOT / "official" / "apps" / "shared").exists())
        self.assertIn('base: "/dashboard/"', (WEB / "vite.config.ts").read_text())

    def test_gateway_serves_official_dashboard_and_not_historical_app(self):
        gateway = (ROOT / "gateway" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"/dashboard"', gateway)
        self.assertIn('"/dashboard/{asset_path:path}"', gateway)
        self.assertNotIn('"/app/{asset_path:path}"', gateway)
        self.assertIn('"/health"', gateway)

    def test_docker_build_uses_official_dashboard_output(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY official official", dockerfile)
        self.assertIn("/web/build/hermes-dashboard", dockerfile)
        self.assertNotIn("artifacts/hermes-web/dist", dockerfile)


if __name__ == "__main__":
    unittest.main()