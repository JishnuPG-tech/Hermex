import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "artifacts" / "hermes-web"


class WebAppContractTests(unittest.TestCase):
    def test_web_app_has_updateable_pwa_entrypoint(self):
        package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["name"], "@workspace/hermes-web")
        self.assertTrue((WEB / "public" / "manifest.webmanifest").exists())
        self.assertTrue((WEB / "public" / "sw.js").exists())

    def test_web_app_uses_existing_webui_stream_contract(self):
        api = (WEB / "src" / "api.ts").read_text(encoding="utf-8")
        app = (WEB / "src" / "App.tsx").read_text(encoding="utf-8")
        for route in (
            "/api/auth/status",
            "/api/sessions",
            "/api/chat/start",
            "/api/chat/stream",
            "/api/chat/cancel",
        ):
            self.assertIn(route, api)
        for event in ("token", "reasoning", "tool_call", "tool_result", "stream_end"):
            self.assertIn(f'"{event}"', api)
        self.assertIn("EventSource", api)
        self.assertIn("Hermex", app)

    def test_gateway_serves_web_app_without_changing_legacy_root(self):
        gateway = (ROOT / "gateway" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"/app"', gateway)
        self.assertIn('"/app/{asset_path:path}"', gateway)
        self.assertIn('"/health"', gateway)


if __name__ == "__main__":
    unittest.main()