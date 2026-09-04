"""Runtime regression coverage for the WebUI adapter.

The tests use a local FastAPI app and a deterministic Hermes SSE stub. They do
not require an upstream model provider or a running Docker container.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_TEMP_ROOT = tempfile.TemporaryDirectory(prefix="hermes-webui-tests-")
_WORKSPACE = Path(_TEMP_ROOT.name) / "workspace"
_WORKSPACE.mkdir()
os.environ["HERMES_WEBUI_PASSWORD"] = "test-password"
os.environ["HERMES_WEBUI_API_KEY"] = "test-bearer-key"
os.environ["HERMES_WEBUI_COOKIE_SECURE"] = "false"
os.environ["HERMES_WEBUI_DATA_DIR"] = str(Path(_TEMP_ROOT.name) / "webui")
os.environ["HERMES_WEBUI_WORKSPACE_BASE"] = str(_WORKSPACE)
os.environ["HERMES_WEBUI_WORKSPACES"] = str(_WORKSPACE)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi import HTTPException

from gateway import sessions_api
import gateway.webui_api as webui


class _FakeStreamResponse:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aiter_lines(self):
        for item in (
            {"type": "thinking", "content": "checking"},
            {"type": "text", "content": "hello"},
            {"type": "text", "content": " world"},
        ):
            yield f"data: {json.dumps(item)}"
        yield "data: [DONE]"


class _FakeAsyncClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, *_args, **_kwargs):
        return _FakeStreamResponse()


class WebUIRuntimeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(webui.router)

    def setUp(self):
        sessions_api._SESSIONS.clear()
        sessions_api._MESSAGES.clear()
        sessions_api._CONV_TO_SESSION.clear()
        webui._WEBUI_STATE["projects"] = []
        webui._WEBUI_STATE["workspaces"] = []
        webui._STREAM_TASKS.clear()
        webui._STREAM_LOCKS.clear()
        self.client = TestClient(self.app)

    def _login(self):
        response = self.client.post("/api/auth/login", json={"password": "test-password"})
        self.assertEqual(response.status_code, 200, response.text)

    def _new_session(self):
        response = self.client.post("/api/session/new", json={"title": "Runtime test"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["session"]["session_id"]

    def test_password_bearer_and_relogin_keep_one_principal(self):
        self._login()
        session_id = self._new_session()
        self.assertEqual(sessions_api._SESSIONS[session_id]["webui_owner"], webui.WEBUI_PRINCIPAL)

        self.client.post("/api/auth/logout")
        self.client.cookies.clear()
        self.client.headers.update({"Authorization": "Bearer test-bearer-key"})
        self.assertEqual(
            self.client.get("/api/session", params={"session_id": session_id}).status_code,
            200,
        )

        self.client.headers.pop("Authorization")
        self.client.post("/api/auth/logout")
        self.client.cookies.clear()
        self._login()
        self.assertEqual(
            self.client.get("/api/session", params={"session_id": session_id}).status_code,
            200,
        )

    def test_other_principal_cannot_access_session(self):
        self._login()
        session_id = self._new_session()
        with self.assertRaises(HTTPException) as raised:
            webui._owned_session(session_id, "other-user")
        self.assertEqual(raised.exception.status_code, 404)

    def test_chat_translates_real_hermes_events_and_replays(self):
        self._login()
        session_id = self._new_session()
        with patch.object(webui.httpx, "AsyncClient", _FakeAsyncClient):
            started = self.client.post(
                "/api/chat/start",
                json={"session_id": session_id, "message": "say hello"},
            )
            self.assertEqual(started.status_code, 200, started.text)
            stream_id = started.json()["stream_id"]
            stream = self.client.get("/api/chat/stream", params={"stream_id": stream_id})

        self.assertEqual(stream.status_code, 200, stream.text)
        self.assertIn("event: reasoning\n", stream.text)
        self.assertIn("event: token\n", stream.text)
        self.assertIn("data: {\"text\":\"hello\"}\n\n", stream.text)
        self.assertIn("event: stream_end\n", stream.text)
        self.assertNotIn("event: tool_call\n", stream.text)

        replay = self.client.get(
            "/api/chat/stream",
            params={"stream_id": stream_id, "after_seq": 2},
        )
        self.assertEqual(replay.status_code, 200)
        self.assertNotIn("event: reasoning\n", replay.text)
        self.assertIn("event: stream_end\n", replay.text)

        messages = self.client.get(
            "/api/session", params={"session_id": session_id}
        ).json()["session"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[-1]["content"], "hello world")

    def test_retry_regenerates_without_duplicating_user_message(self):
        self._login()
        session_id = self._new_session()
        with patch.object(webui.httpx, "AsyncClient", _FakeAsyncClient):
            started = self.client.post(
                "/api/chat/start",
                json={"session_id": session_id, "message": "retry me"},
            )
            self.client.get(
                "/api/chat/stream",
                params={"stream_id": started.json()["stream_id"]},
            )
            retried = self.client.post(
                "/api/session/retry", json={"session_id": session_id}
            )
            self.assertEqual(retried.status_code, 200, retried.text)
            self.client.get(
                "/api/chat/stream",
                params={"stream_id": retried.json()["stream_id"]},
            )

        messages = self.client.get(
            "/api/session", params={"session_id": session_id}
        ).json()["session"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["content"], "retry me")

    def test_undo_removes_the_last_complete_turn(self):
        self._login()
        session_id = self._new_session()
        sessions_api._MESSAGES[session_id] = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "answer"},
        ]
        result = self.client.post(
            "/api/session/undo", json={"session_id": session_id}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["removed_count"], 2)
        self.assertEqual(sessions_api._MESSAGES[session_id], [])

    def test_cancel_authorizes_stream_and_cancels_task(self):
        self._login()
        session_id = self._new_session()
        stream_id = "cancel-test-stream"
        webui._write_stream_meta(
            stream_id,
            {
                "stream_id": stream_id,
                "session_id": session_id,
                "owner": webui.WEBUI_PRINCIPAL,
                "status": "running",
                "seq": 0,
            },
        )

        class Task:
            def __init__(self):
                self.cancelled = False

            def done(self):
                return False

            def cancel(self):
                self.cancelled = True

        task = Task()
        webui._STREAM_TASKS[stream_id] = task
        result = self.client.post(
            "/api/chat/cancel", params={"stream_id": stream_id}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(task.cancelled)
        self.assertTrue(webui._read_stream_meta(stream_id)["cancel_requested"])

    def test_stream_metadata_recreates_missing_stream_directory(self):
        stream_id = "missing-stream-dir"
        missing_directory = Path(_TEMP_ROOT.name) / "webui-missing" / "streams"
        with patch.object(webui, "_STREAMS_DIR", missing_directory):
            webui._write_stream_meta(stream_id, {"stream_id": stream_id, "status": "starting"})

            self.assertTrue(missing_directory.is_dir())
            self.assertEqual(
                webui._read_stream_meta(stream_id)["status"],
                "starting",
            )

    def test_workspace_traversal_and_symlink_escape_are_blocked(self):
        self._login()
        session_id = self._new_session()
        outside = Path(_TEMP_ROOT.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        (_WORKSPACE / "inside.txt").write_text("safe", encoding="utf-8")
        (_WORKSPACE / "link.txt").symlink_to(outside)

        traversal = self.client.get(
            "/api/file",
            params={"session_id": session_id, "path": "../outside.txt"},
        )
        self.assertEqual(traversal.status_code, 400)
        absolute = self.client.get(
            "/api/file",
            params={"session_id": session_id, "path": str(outside)},
        )
        self.assertEqual(absolute.status_code, 400)
        escaped = self.client.get(
            "/api/file",
            params={"session_id": session_id, "path": "link.txt"},
        )
        self.assertEqual(escaped.status_code, 403)
        secret = self.client.get(
            "/api/file",
            params={"session_id": session_id, "path": ".env"},
        )
        self.assertEqual(secret.status_code, 403)


if __name__ == "__main__":
    unittest.main()