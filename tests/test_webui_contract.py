"""Dependency-light regression checks for the additive WebUI adapter."""
from pathlib import Path
import ast
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "gateway" / "webui_api.py"
MAIN = ROOT / "gateway" / "main.py"

REQUIRED_WEBUI_ROUTES = {
    "/api/auth/status", "/api/auth/login", "/api/auth/logout",
    "/api/sessions", "/api/session", "/api/session/status",
    "/api/session/new", "/api/session/rename", "/api/session/delete",
    "/api/session/pin", "/api/session/archive", "/api/session/move",
    "/api/session/branch", "/api/session/truncate", "/api/session/usage",
    "/api/projects", "/api/projects/create", "/api/chat/start",
    "/api/chat/stream", "/api/chat/cancel", "/api/chat/stream/status",
    "/api/chat/steer", "/api/upload", "/api/upload/extract",
    "/api/workspaces", "/api/workspaces/suggest", "/api/list",
    "/api/file", "/api/file/raw", "/api/models", "/api/providers",
    "/api/settings", "/api/default-model", "/api/reasoning", "/api/profiles",
}


def route_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        for decorator in getattr(node, "decorator_list", []):
            if isinstance(decorator, ast.Call) and decorator.args:
                first = decorator.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value)
    return found


class WebUICompatibilityRegressionTests(unittest.TestCase):
    def test_required_webui_routes_are_declared(self):
        self.assertTrue(WEBUI.exists())
        self.assertTrue(REQUIRED_WEBUI_ROUTES <= route_literals(WEBUI))

    def test_existing_router_registration_remains(self):
        source = MAIN.read_text(encoding="utf-8")
        for marker in (
            "app.include_router(v1_sessions_router)",
            "app.include_router(claude_rest_router)",
            "app.include_router(hermes_proxy_router)",
            "app.include_router(webui_router)",
        ):
            self.assertIn(marker, source)
        self.assertLess(source.index("app.include_router(webui_router)"), source.index("app.include_router(claude_rest_router)"))

    def test_adapter_does_not_add_v1_routes(self):
        routes = route_literals(WEBUI)
        self.assertFalse(any(path == "/v1" or path.startswith("/v1/") for path in routes))

    def test_example_contains_no_credential_literal(self):
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"sk-[0-9a-f]{16,}", env_example, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
