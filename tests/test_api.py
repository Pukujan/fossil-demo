from __future__ import annotations

import hashlib
import sqlite3

from fastapi.testclient import TestClient

from conftest import create_workspace, establish, valid_share_url


def test_session_cookie_is_secure_and_only_hash_is_stored(client_factory):
    client, _, settings = client_factory()
    response = client.post("/api/v0/session")
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"]
    assert "__Host-fossil_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert "Path=/" in cookie_header

    secret = client.cookies.get("__Host-fossil_session")
    assert secret
    expected_hash = hashlib.sha256(secret.encode()).hexdigest()
    with sqlite3.connect(settings.db_path) as conn:
        row = conn.execute("SELECT session_hash FROM sessions").fetchone()
    assert row == (expected_hash,)
    assert secret not in settings.db_path.read_bytes().decode("latin-1", errors="ignore")


def test_workspace_requires_session(client_factory):
    client, _, _ = client_factory()
    response = client.post("/api/v0/workspaces", json={})
    assert response.status_code == 401


def test_cross_tenant_workspace_isolation(client_factory):
    client_a, app, _ = client_factory()
    establish(client_a)
    workspace_id = create_workspace(client_a)

    client_b = TestClient(app, base_url="https://testserver")
    establish(client_b)
    assert client_b.get(f"/api/v0/workspaces/{workspace_id}").status_code == 404
    assert client_b.delete(f"/api/v0/workspaces/{workspace_id}").status_code == 404

    no_session = TestClient(app, base_url="https://testserver")
    assert no_session.get(f"/api/v0/workspaces/{workspace_id}").status_code == 401

    assert client_a.get(f"/api/v0/workspaces/{workspace_id}").status_code == 200


def test_rejects_unsupported_share_url_before_processing(client_factory):
    client, _, _ = client_factory()
    establish(client)
    workspace_id = create_workspace(client)
    response = client.post(
        f"/api/v0/workspaces/{workspace_id}/sources",
        json={"kind": "chatgpt_share", "url": "https://example.com/share/nope"},
    )
    assert response.status_code == 422
    state = client.get(f"/api/v0/workspaces/{workspace_id}").json()
    assert state["workspace"]["status"] == "ready"
    assert state["source"] is None


def test_complete_fixture_runs_vertical_slice(client_factory):
    client, _, _ = client_factory("complete")
    establish(client)
    workspace_id = create_workspace(client)

    accepted = client.post(
        f"/api/v0/workspaces/{workspace_id}/sources",
        json={"kind": "chatgpt_share", "url": valid_share_url()},
    )
    assert accepted.status_code == 202
    assert accepted.json()["workspace"] == {"status": "processing", "memory_status": "building"}

    state = client.get(f"/api/v0/workspaces/{workspace_id}")
    assert state.status_code == 200
    body = state.json()
    assert body["source"]["capture_status"] == "complete"
    assert body["source"]["completeness"] == "complete"
    assert body["source"]["ingestion"]["status"] == "ingested"
    assert body["workspace"]["memory_status"] == "ready"
    assert all(stage["status"] == "passed" for stage in body["stages"])

    memory = client.get(f"/api/v0/workspaces/{workspace_id}/memory")
    assert memory.status_code == 200
    assert memory.json()["memory"]["capabilities"]["semantic_claims"] is False

    query = client.post(
        f"/api/v0/workspaces/{workspace_id}/queries",
        json={"query": "FOSSIL", "mode": "grounded"},
    )
    assert query.status_code == 200
    result = query.json()
    assert result["answer"]["generated"] is False
    assert result["evidence"]
    assert result["lineage"]["kind"] == "structural_reconstruction"

    citation_id = result["evidence"][0]["citation_id"]
    evidence = client.get(f"/api/v0/workspaces/{workspace_id}/evidence/{citation_id}")
    assert evidence.status_code == 200

    lineage_ref = result["lineage"]["current_ref"]
    lineage = client.get(f"/api/v0/workspaces/{workspace_id}/lineage/{lineage_ref}")
    assert lineage.status_code == 200
    assert lineage.json()["lineage"]["kind"] == "structural_reconstruction"

    verify = client.get(f"/api/v0/workspaces/{workspace_id}/verify")
    assert verify.status_code == 200
    verified = verify.json()["verification"]
    assert verified["status"] == "verified"
    assert verified["checks"]["capture_complete"] is True


def test_incomplete_fixture_preserves_evidence_and_refuses_memory(client_factory):
    client, _, _ = client_factory("incomplete")
    establish(client)
    workspace_id = create_workspace(client)

    response = client.post(
        f"/api/v0/workspaces/{workspace_id}/sources",
        json={"kind": "chatgpt_share", "url": valid_share_url()},
    )
    assert response.status_code == 202

    state = client.get(f"/api/v0/workspaces/{workspace_id}").json()
    assert state["source"]["capture_status"] == "incomplete"
    assert state["source"]["evidence_preserved"] is True
    assert state["source"]["ingestion"]["status"] == "refused"
    stage = {item["id"]: item["status"] for item in state["stages"]}
    assert stage["evidence"] == "passed"
    assert stage["completeness"] == "refused"
    assert stage["ingest"] == "refused"
    assert stage["query"] == "skipped"

    assert client.get(f"/api/v0/workspaces/{workspace_id}/memory").status_code == 409
    assert client.post(
        f"/api/v0/workspaces/{workspace_id}/queries",
        json={"query": "FOSSIL", "mode": "grounded"},
    ).status_code == 409

    verify = client.get(f"/api/v0/workspaces/{workspace_id}/verify")
    assert verify.status_code == 200
    assert verify.json()["verification"]["status"] == "not_verified"
    assert verify.json()["verification"]["checks"]["source_binding"] is True


def test_delete_now_removes_owned_workspace_and_directory(client_factory):
    client, _, settings = client_factory()
    establish(client)
    workspace_id = create_workspace(client)
    root = settings.workspace_root / workspace_id
    assert root.exists()

    response = client.delete(f"/api/v0/workspaces/{workspace_id}")
    assert response.status_code == 204
    assert not root.exists()
    assert client.get(f"/api/v0/workspaces/{workspace_id}").status_code == 404
