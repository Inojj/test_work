from uuid import uuid4

from httpx import AsyncClient


async def _create(client: AsyncClient, **overrides) -> dict:
    body = {"title": "demo task", "priority": "MEDIUM"}
    body.update(overrides)
    resp = await client.post("/api/v1/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_task_returns_201_pending(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/tasks", json={"title": "ingest", "priority": "HIGH"}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "ingest"
    assert body["priority"] == "HIGH"
    assert body["status"] == "PENDING"
    assert body["id"]
    assert body["started_at"] is None
    assert body["finished_at"] is None


async def test_create_task_defaults_priority_medium(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/tasks", json={"title": "x"})
    assert resp.status_code == 201
    assert resp.json()["priority"] == "MEDIUM"


async def test_get_task_by_id_200(client: AsyncClient) -> None:
    created = await _create(client)
    resp = await client.get(f"/api/v1/tasks/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


async def test_get_task_missing_404(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/tasks/{uuid4()}")
    assert resp.status_code == 404
    assert "detail" in resp.json()


async def test_get_status_endpoint(client: AsyncClient) -> None:
    created = await _create(client)
    resp = await client.get(f"/api/v1/tasks/{created['id']}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"id": created["id"], "status": "PENDING"}


async def test_list_pagination_limit_offset_total(client: AsyncClient) -> None:
    for i in range(5):
        await _create(client, title=f"t{i}")

    resp = await client.get("/api/v1/tasks", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    resp2 = await client.get("/api/v1/tasks", params={"limit": 2, "offset": 4})
    assert len(resp2.json()["items"]) == 1


async def test_list_filter_by_status(client: AsyncClient) -> None:
    created = await _create(client)
    await _create(client)
    await client.delete(f"/api/v1/tasks/{created['id']}")

    resp = await client.get("/api/v1/tasks", params={"status": "CANCELLED"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "CANCELLED"

    pending = await client.get("/api/v1/tasks", params={"status": "PENDING"})
    assert pending.json()["total"] == 1


async def test_list_filter_by_priority(client: AsyncClient) -> None:
    await _create(client, priority="LOW")
    await _create(client, priority="HIGH")
    await _create(client, priority="HIGH")

    resp = await client.get("/api/v1/tasks", params={"priority": "HIGH"})
    body = resp.json()
    assert body["total"] == 2
    assert all(item["priority"] == "HIGH" for item in body["items"])


async def test_cancel_task_200_then_409(client: AsyncClient) -> None:
    created = await _create(client)

    first = await client.delete(f"/api/v1/tasks/{created['id']}")
    assert first.status_code == 200
    assert first.json()["status"] == "CANCELLED"

    second = await client.delete(f"/api/v1/tasks/{created['id']}")
    assert second.status_code == 409
    assert "detail" in second.json()


async def test_cancel_missing_404(client: AsyncClient) -> None:
    resp = await client.delete(f"/api/v1/tasks/{uuid4()}")
    assert resp.status_code == 404


async def test_create_empty_title_422(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/tasks", json={"title": ""})
    assert resp.status_code == 422


async def test_create_bad_priority_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/tasks", json={"title": "x", "priority": "URGENT"}
    )
    assert resp.status_code == 422


async def test_list_bad_limit_422(client: AsyncClient) -> None:
    too_high = await client.get("/api/v1/tasks", params={"limit": 1000})
    assert too_high.status_code == 422

    too_low = await client.get("/api/v1/tasks", params={"limit": 0})
    assert too_low.status_code == 422

    neg_offset = await client.get("/api/v1/tasks", params={"offset": -1})
    assert neg_offset.status_code == 422
