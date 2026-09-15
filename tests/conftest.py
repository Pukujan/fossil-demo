from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fossil_demo.app import create_app
from fossil_demo.capture import FixtureCaptureAdapter
from fossil_demo.config import Settings


@pytest.fixture
def app_factory(tmp_path: Path):
    def factory(outcome: str = "complete"):
        settings = Settings(
            db_path=tmp_path / outcome / "demo.sqlite",
            workspace_root=tmp_path / outcome / "workspaces",
            cookie_secure=True,
        )
        app = create_app(settings=settings, capture_adapter=FixtureCaptureAdapter(outcome))
        return app, settings

    return factory


@pytest.fixture
def client_factory(app_factory):
    def factory(outcome: str = "complete"):
        app, settings = app_factory(outcome)
        return TestClient(app, base_url="https://testserver"), app, settings

    return factory


def establish(client: TestClient) -> None:
    response = client.post("/api/v0/session")
    assert response.status_code == 200


def create_workspace(client: TestClient) -> str:
    response = client.post("/api/v0/workspaces", json={})
    assert response.status_code == 201
    return response.json()["workspace"]["workspace_id"]


def valid_share_url() -> str:
    return "https://chatgpt.com/share/6aa7eabe-92b4-83ea-899b-7c11fb3fcf58"
