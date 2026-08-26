"""Request-ID middleware: echo trusted ids, generate otherwise, never echo unsafe."""

from httpx import AsyncClient


async def test_generates_unique_ids_when_header_missing(client: AsyncClient) -> None:
    first = await client.get("/healthz")
    second = await client.get("/healthz")

    first_id = first.headers["x-request-id"]
    second_id = second.headers["x-request-id"]
    assert len(first_id) == 32  # uuid4().hex
    assert first_id != second_id


async def test_incoming_request_id_echoed(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"


async def test_unsafe_characters_stripped_from_echo(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "bad id"})
    echoed = response.headers["x-request-id"]
    assert echoed == "badid"
    assert all(0x21 <= ord(ch) <= 0x7E for ch in echoed)


async def test_oversized_request_id_truncated(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "a" * 500})
    assert response.headers["x-request-id"] == "a" * 64
