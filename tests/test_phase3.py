"""Functional coverage for the Phase 3 WebUI resources."""
import os
import tempfile
import unittest
from pathlib import Path


_TEMP_ROOT = tempfile.TemporaryDirectory(prefix="hermes-phase3-tests-")
os.environ["HERMES_WEBUI_PASSWORD"] = "test-password"
os.environ["HERMES_WEBUI_API_KEY"] = ""
os.environ["HERMES_WEBUI_COOKIE_SECURE"] = "false"
os.environ["HERMES_WEBUI_DATA_DIR"] = str(Path(_TEMP_ROOT.name) / "webui")
os.environ["HERMES_MEMORY_DB"] = str(Path(_TEMP_ROOT.name) / "memory.sqlite")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway import sessions_api
import gateway.webui_api as webui


class Phase3ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(webui.router)

    def setUp(self):
        sessions_api._SESSIONS.clear()
        sessions_api._MESSAGES.clear()
        sessions_api._CONV_TO_SESSION.clear()
        for key in ("projects", "memory", "goals", "tasks", "files", "workspaces"):
            webui._WEBUI_STATE[key] = []
        self.client = TestClient(self.app)

    def login(self):
        response = self.client.post("/api/auth/login", json={"password": "test-password"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_resources_require_authentication(self):
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/memory").status_code, 401)
        self.assertEqual(self.client.get("/api/goals").status_code, 401)
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)

    def test_project_memory_goal_and_dependency_graph_persist(self):
        self.login()
        project_response = self.client.post(
            "/api/projects",
            json={
                "name": "Hermex Phase 3",
                "description": "Persistent agent workspace",
                "instructions": "Keep changes compatible with the frozen APK.",
            },
        )
        self.assertEqual(project_response.status_code, 200, project_response.text)
        project = project_response.json()["project"]
        project_id = project["project_id"]
        self.assertEqual(project["session_count"], 0)

        updated = self.client.patch(
            f"/api/projects/{project_id}",
            json={"description": "Updated description"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["project"]["description"], "Updated description")
        project_session = self.client.post(
            "/api/session/new",
            json={"title": "Project conversation", "project_id": project_id},
        )
        self.assertEqual(project_session.status_code, 200, project_session.text)
        self.assertEqual(project_session.json()["session"]["project_id"], project_id)

        memory = self.client.post(
            f"/api/projects/{project_id}/memory",
            json={"content": "The web app is the updateable client.", "category": "architecture"},
        )
        self.assertEqual(memory.status_code, 200, memory.text)
        memory_id = memory.json()["memory"]["id"]
        self.assertEqual(
            self.client.get(f"/api/projects/{project_id}/memory").json()["count"],
            1,
        )
        self.assertEqual(
            self.client.patch(f"/api/memory/{memory_id}", json={"content": "The web app is updateable."}).status_code,
            200,
        )
        self.assertEqual(self.client.delete(f"/api/memory/{memory_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/memory").json()["count"], 0)

        goal = self.client.post(
            f"/api/projects/{project_id}/goals",
            json={"title": "Ship Phase 3", "status": "ACTIVE"},
        )
        self.assertEqual(goal.status_code, 200, goal.text)
        goal_id = goal.json()["goal"]["id"]

        first = self.client.post(
            f"/api/goals/{goal_id}/tasks",
            json={"title": "Implement storage"},
        )
        second = self.client.post(
            f"/api/goals/{goal_id}/tasks",
            json={"title": "Verify persistence", "dependencies": [first.json()["task"]["id"]]},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        first_id = first.json()["task"]["id"]
        second_id = second.json()["task"]["id"]
        self.assertEqual(first.json()["task"]["status"], "READY")
        self.assertEqual(second.json()["task"]["status"], "PENDING")

        blocked_start = self.client.post(f"/api/tasks/{second_id}/start")
        self.assertEqual(blocked_start.status_code, 409, blocked_start.text)
        complete_first = self.client.patch(
            f"/api/tasks/{first_id}",
            json={"status": "COMPLETED", "result": "Stored"},
        )
        self.assertEqual(complete_first.status_code, 200, complete_first.text)
        tasks = self.client.get(f"/api/projects/{project_id}/tasks").json()["tasks"]
        self.assertEqual(next(item for item in tasks if item["id"] == second_id)["status"], "READY")

        self.assertEqual(self.client.post(f"/api/tasks/{second_id}/start").status_code, 200)
        self.assertEqual(
            self.client.patch(f"/api/tasks/{second_id}", json={"status": "COMPLETED"}).status_code,
            200,
        )
        goal_detail = self.client.get(f"/api/goals/{goal_id}").json()["goal"]
        self.assertEqual(goal_detail["progress"], 100)
        self.assertEqual(goal_detail["completed_task_count"], 2)

        detail = self.client.get(f"/api/projects/{project_id}").json()["project"]
        self.assertEqual(len(detail["goals"]), 1)
        self.assertEqual(len(detail["tasks"]), 2)

    def test_wrong_owner_cannot_read_phase3_resources(self):
        self.login()
        project = self.client.post("/api/projects", json={"name": "Private"}).json()["project"]
        memory = self.client.post("/api/memory", json={"content": "private"}).json()["memory"]
        with self.assertRaises(Exception):
            webui._owned_project(project["project_id"], "other-user")
        with self.assertRaises(Exception):
            webui._phase3_item("memory", memory["id"], "other-user")


if __name__ == "__main__":
    unittest.main()