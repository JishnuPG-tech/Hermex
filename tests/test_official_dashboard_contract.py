"""Regression checks for the upstream dashboard/API compatibility boundary."""
from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "gateway" / "main.py"
API = ROOT / "gateway" / "hermes_dashboard_api.py"


def route_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes = set()
    for node in ast.walk(tree):
        for decorator in getattr(node, "decorator_list", []):
            if isinstance(decorator, ast.Call) and decorator.args:
                value = decorator.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    routes.add(value.value)
    return routes


class OfficialDashboardContractTests(unittest.TestCase):
    def test_static_dashboard_and_spa_routes_exist(self):
        routes = route_literals(MAIN)
        self.assertIn("/dashboard", routes)
        self.assertIn("/dashboard/{asset_path:path}", routes)
        self.assertIn("/login", routes)

    def test_api_compatibility_routes_exist(self):
        routes = route_literals(API)
        for path in (
            "/api/status",
            "/api/auth/me",
            "/api/auth/ws-ticket",
            "/api/sessions/{session_id}",
            "/api/sessions/{session_id}/messages",
            "/api/config",
            "/api/config/defaults",
            "/api/config/schema",
            "/api/model/info",
            "/api/model/options",
            "/api/events",
            "/api/ws",
            "/api/pty",
        ):
            self.assertIn(path, routes)

    def test_compatibility_layer_has_no_shell_subprocess_bridge(self):
        source = API.read_text(encoding="utf-8")
        self.assertNotIn("subprocess.", source)
        self.assertNotIn("os.system(", source)
        self.assertIn("feature_not_supported", source)


if __name__ == "__main__":
    unittest.main()