"""Static regression checks for the additive WebUI adapter.

These checks intentionally avoid importing the service so they can run in a
minimal checkout as well as inside the production image.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEBUI = (ROOT / "gateway" / "webui_api.py").read_text(encoding="utf-8")
MAIN = (ROOT / "gateway" / "main.py").read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")


class WebUISecurityRegressionTests(unittest.TestCase):
    def test_sse_uses_real_line_delimiters(self):
        self.assertIn("yield f\"id: {stream_id}:{last_seq}\\nevent:", WEBUI)
        self.assertNotIn("last_seq}\\\\nevent:", WEBUI)

    def test_sensitive_files_are_blocked(self):
        for marker in ("_SENSITIVE_NAMES", "_safe_upload_name", "Path traversal is not allowed"):
            self.assertIn(marker, WEBUI)
        self.assertIn("Access to private files is not allowed", WEBUI)

    def test_streams_can_be_cancelled_at_task_level(self):
        self.assertIn("_STREAM_TASKS", WEBUI)
        self.assertIn("task.cancel()", WEBUI)

    def test_webui_router_is_registered_once_and_legacy_proxy_is_retained(self):
        self.assertEqual(MAIN.count("app.include_router(webui_router)"), 1)
        self.assertIn("app.include_router(v1_sessions_router)", MAIN)
        self.assertIn("app.include_router(hermes_proxy_router)", MAIN)

    def test_gateway_runs_one_worker_for_process_local_stream_state(self):
        self.assertIn("--workers 1", ENTRYPOINT)
        self.assertNotIn("--workers 2", ENTRYPOINT)

    def test_repository_has_no_known_committed_credential_literals(self):
        for path in ROOT.rglob("*"):
            if not path.is_file() or "Frontend" in path.parts or ".git" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            forbidden_marker = "Tfb" + "VB8"
            self.assertIsNone(re.search(r"sk-[0-9a-f]{16,}|" + forbidden_marker, text, re.IGNORECASE), str(path))


if __name__ == "__main__":
    unittest.main()