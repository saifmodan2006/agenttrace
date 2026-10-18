import uuid
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.memory.manager import AgentMemoryManager


@pytest.fixture
def client(monkeypatch):
    name = "api-" + uuid.uuid4().hex
    monkeypatch.setattr(settings, "tenant_tokens", name + ":test-token," + name + "-other:other-token")
    monkeypatch.setenv("EMBEDDED_WORKER", "0")
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer test-token"
        yield c
    for tenant in [name, name + "-other"]:
        AgentMemoryManager(tenant).store.graph.delete()


def test_api_auth_isolation_and_validated_ids(client):
    assert client.get("/api/runs", headers={"Authorization": "Bearer nope"}).status_code == 401
    response = client.post("/api/runs", json={"goal": "Repair sample calculator"})
    assert response.status_code == 201, response.text
    run = response.json()["data"]
    assert (
        client.get("/api/runs/" + run["id"], headers={"Authorization": "Bearer other-token"}).status_code
        == 404
    )
    assert client.get("/api/runs/not-a-uuid").status_code == 422
    assert client.post("/api/runs", json={"goal": "x"}).status_code == 422


def test_api_run_controls_worker_auth_and_openapi(client):
    run = client.post("/api/runs", json={"goal": "Repair sample calculator"}).json()["data"]
    rid = run["id"]
    assert client.post("/api/runs/" + rid + "/start").status_code == 200
    ready = client.get("/api/runs/" + rid + "/ready").json()["data"]
    step = ready[0]["step"]
    body = {"run_id": rid, "step_id": step["id"], "worker_id": "api-worker"}
    assert client.post("/api/internal/claim", json=body).status_code == 403
    headers = {"X-Worker-Token": settings.worker_token}
    claimed = client.post("/api/internal/claim", json=body, headers=headers)
    assert claimed.status_code == 200, claimed.text
    assert client.post("/api/internal/claim", json=body, headers=headers).status_code == 409
    c = claimed.json()["data"]
    lease = {
        "step_id": step["id"],
        "attempt_id": c["attempt"]["id"],
        "lease_token": c["attempt"]["lease_token"],
        "worker_id": "api-worker",
    }
    assert client.post("/api/internal/heartbeat", json=lease, headers=headers).status_code == 200
    assert client.post("/api/internal/attempts/complete", json=lease, headers=headers).status_code == 200
    assert client.get("/api/steps/" + step["id"] + "/attempts").json()["data"][0]["status"] == "succeeded"
    assert client.post("/api/runs/" + rid + "/pause").status_code == 200
    assert client.post("/api/runs/" + rid + "/resume").json()["data"]["checkpoint"]
    for path in ["graph", "events", "explanations", "checkpoint", "steps"]:
        assert client.get("/api/runs/" + rid + "/" + path).status_code == 200
    for path in [
        "/api/memory/search",
        "/api/memory/procedures",
        "/api/agents",
        "/api/config/status",
        "/api/overview",
        "/openapi.json",
    ]:
        assert client.get(path).status_code == 200


def test_unconfigured_model_rejected(client):
    response = client.post("/api/runs", json={"goal": "Repair sample calculator", "mode": "llm"})
    if not settings.llm_base_url:
        assert response.status_code == 422
