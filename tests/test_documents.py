"""Day-2 integration tests for document upload.

Each upload is content-addressed on disk under DATA_DIR; the fixtures point
DATA_DIR at a per-test tmp_path and wipe the documents table afterwards so
tests are independent of each other and repeatable across runs.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select

import app.db as db
from app.config import get_settings
from app.models.document import Document

PDF_MIME = "application/pdf"
TEXT_MIME = "text/plain"


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def clean_documents(client: AsyncClient) -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(Document))
        await session.commit()


async def upload(
    client: AsyncClient, content: bytes, mime: str = TEXT_MIME, filename: str = "a.txt"
):
    return await client.post(
        "/documents",
        files={"file": (filename, content, mime)},
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )


async def document_count() -> int:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        count = await session.scalar(select(func.count()).select_from(Document))
    assert count is not None
    return count


async def test_upload_happy_path(client: AsyncClient, tmp_path: Path) -> None:
    tenant_id = uuid.uuid4()
    content = b"master services agreement v1"

    response = await client.post(
        "/documents",
        files={"file": ("msa.txt", content, TEXT_MIME)},
        headers={"X-Tenant-Id": str(tenant_id)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "msa.txt"
    assert body["mime_type"] == TEXT_MIME
    assert body["status"] == "uploaded"
    assert body["tenant_id"] == str(tenant_id)

    sha256 = hashlib.sha256(content).hexdigest()
    assert body["sha256"] == sha256

    stored = tmp_path / str(tenant_id) / sha256
    assert stored.read_bytes() == content

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        row = await session.get(Document, uuid.UUID(body["id"]))
    assert row is not None
    assert row.sha256 == sha256


async def test_duplicate_content_same_tenant_conflict(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    content = b"amendment one"
    headers = {"X-Tenant-Id": str(tenant_id)}

    first = await client.post(
        "/documents",
        files={"file": ("a.txt", content, TEXT_MIME)},
        headers=headers,
    )
    second = await client.post(
        "/documents",
        files={"file": ("renamed.txt", content, TEXT_MIME)},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    existing_id = second.json()["detail"]["existing_id"]
    assert existing_id == first.json()["id"]

    # Same bytes in another tenant are not a conflict: uniqueness is per tenant.
    other = await upload(client, content)
    assert other.status_code == 201


async def test_invalid_mime_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/documents",
        files={"file": ("x.exe", b"MZ...", "application/x-msdownload")},
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )

    assert response.status_code == 415
    assert "unsupported media type" in response.json()["detail"]
    assert await document_count() == 0


async def test_missing_tenant_header_rejected(client: AsyncClient) -> None:
    response = await client.post("/documents", files={"file": ("a.txt", b"x", TEXT_MIME)})
    assert response.status_code == 422
    assert await document_count() == 0


async def test_pdf_allowed(client: AsyncClient) -> None:
    response = await upload(client, b"%PDF-1.7", PDF_MIME, "contract.pdf")
    assert response.status_code == 201
