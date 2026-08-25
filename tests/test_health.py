from fastapi import status
from httpx import AsyncClient


async def test_healthz_is_ok_when_postgres_is_up(client: AsyncClient) -> None:
    resp = await client.get("/healthz")

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["version"]
