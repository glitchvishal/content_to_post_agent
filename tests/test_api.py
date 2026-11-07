import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from .conftest import ARTICLE


@pytest.fixture
def client(settings, graph):
    with TestClient(create_app(settings=settings, graph=graph)) as c:
        yield c


def _wait_for(client, run_id, statuses, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(f"run never reached {statuses}: {body['status']}")


def test_full_run_with_review(client):
    response = client.post("/runs", json={"text": ARTICLE})
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    body = _wait_for(client, run_id, {"awaiting_review"})
    assert set(body["posts"]) == {"linkedin", "x"}
    assert body["revisions"] == 1 and body["usage"]["llm_calls"] == 9

    # The SSE stream replays every event and ends at the review pause.
    stream = client.get(f"/runs/{run_id}/events").text
    for expected in ("event: node", '"node": "critique"', "event: review_required", '"status": "awaiting_review"'):
        assert expected in stream

    final = client.post(f"/runs/{run_id}/review", json={"decision": "approve"}).json()
    assert final["status"] == "completed"
    assert len(final["scheduled"]) == 2

    # Reviewing twice is a conflict, not a second scheduling.
    assert client.post(f"/runs/{run_id}/review", json={"decision": "approve"}).status_code == 409


def test_invalid_edit_returns_422_and_run_stays_paused(client):
    run_id = client.post("/runs", json={"text": ARTICLE}).json()["run_id"]
    _wait_for(client, run_id, {"awaiting_review"})
    response = client.post(f"/runs/{run_id}/review", json={"decision": "edit", "posts": {"x": "a" * 400}})
    assert response.status_code == 422
    assert client.get(f"/runs/{run_id}").json()["status"] == "awaiting_review"


def test_failed_run_reports_clear_error(client):
    run_id = client.post("/runs", json={"text": "Way too short."}).json()["run_id"]
    body = _wait_for(client, run_id, {"failed"})
    assert body["error"]["type"] == "content_error"
    assert body["error"]["node"] == "fetch_and_chunk"


def test_request_validation(client):
    assert client.post("/runs", json={}).status_code == 422
    assert client.post("/runs", json={"text": ARTICLE, "url": "https://example.com"}).status_code == 422
    assert client.post("/runs", json={"text": ARTICLE, "platforms": ["tiktok"]}).status_code == 422
    assert client.get("/runs/does-not-exist").status_code == 404
    assert client.get("/health").json()["status"] == "ok"


def test_cors_allows_the_web_origin(client):
    headers = {"Origin": "http://localhost:3001", "Access-Control-Request-Method": "POST"}
    response = client.options("/runs", headers=headers)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3001"
    blocked = client.options("/runs", headers={**headers, "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers
