"""Dependency-free regression checks for Hermes server-side agent capabilities."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = ROOT / "hermes_core" / "tools" / "terminal_tools.py"
REGISTRY = ROOT / "hermes_core" / "tools" / "registry.py"
AGENT = ROOT / "hermes_core" / "agent.py"
DOCKERFILE = ROOT / "Dockerfile"
WEBUI = ROOT / "gateway" / "webui_api.py"
BRIDGE = ROOT / "Backend" / "gateway" / "anthropic_bridge.py"
PROXY = ROOT / "gateway" / "hermes_proxy.py"


class HermesServerCapabilityTests(unittest.TestCase):
    def test_bash_tool_exposes_server_controls(self):
        source = TERMINAL.read_text(encoding="utf-8")
        for marker in (
            "directly on the Hermes Agent server",
            "working_directory",
            "timeout_seconds",
            "max_output_chars",
            'executable="/bin/bash"',
            "start_new_session=True",
        ):
            self.assertIn(marker, source)

    def test_server_operations_select_the_coding_tools(self):
        source = REGISTRY.read_text(encoding="utf-8")
        for keyword in ("install", "git", "clone", "push", "read", "write", "deploy"):
            self.assertIn(f'"{keyword}"', source)
        self.assertIn("selected_categories.add(\"coding\")", source)

    def test_tool_results_are_returned_to_the_next_agent_round(self):
        tree = ast.parse(AGENT.read_text(encoding="utf-8"))
        roles = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("tool", roles)
        self.assertIn("tool_call_id", roles)
        self.assertIn("MAX_TOOL_ROUNDS", AGENT.read_text(encoding="utf-8"))

    def test_runtime_image_includes_git(self):
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("    git \\", dockerfile)
        self.assertIn("HERMES_SERVER_WORKDIR=/app", dockerfile)

    def test_stream_storage_is_recreated_at_point_of_use(self):
        source = WEBUI.read_text(encoding="utf-8")
        self.assertIn("_STREAMS_DIR.mkdir(parents=True, exist_ok=True)", source)

    def test_empty_internal_keys_do_not_create_invalid_bearer_headers(self):
        agent = AGENT.read_text(encoding="utf-8")
        bridge = BRIDGE.read_text(encoding="utf-8")
        proxy = PROXY.read_text(encoding="utf-8")
        self.assertIn("if self.api_key:", agent)
        self.assertIn('if UPSTREAM_KEY else {}', bridge)
        self.assertIn("if API_SERVER_KEY.strip():", proxy)


if __name__ == "__main__":
    unittest.main()
