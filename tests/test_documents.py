"""Day-2 integration tests for document upload.

Each upload is content-addressed on disk under DATA_DIR; the fixtures point
DATA_DIR at a per-test tmp_path and wipe the documents table afterwards so
tests are independent of each other and repeatable across runs.
"""

import hashlib
import io
import uuid
import zipfile
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
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_bytes() -> bytes:
    """Minimal real OOXML package: ZIP with [Content_Types].xml + word/ parts."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("[Content_Types].xml", "<Types/>")
        bundle.writestr("word/document.xml", "<doc/>")
    return buffer.getvalue()


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


async def test_list_empty_tenant(client: AsyncClient) -> None:
    response = await client.get("/documents", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_list_newest_first_and_tenant_isolated(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    first = await client.post(
        "/documents", files={"file": ("a.txt", b"first", TEXT_MIME)}, headers=headers
    )
    second = await client.post(
        "/documents", files={"file": ("b.txt", b"second", TEXT_MIME)}, headers=headers
    )
    await upload(client, b"other tenants bytes")  # must not appear in the list below

    response = await client.get("/documents", headers=headers)
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [
        second.json()["id"],
        first.json()["id"],
    ]


async def test_list_pagination_window(client: AsyncClient) -> None:
    headers = {"X-Tenant-Id": str(uuid.uuid4())}
    ids = [
        (
            await client.post(
                "/documents",
                files={"file": (f"{n}.txt", f"bytes-{n}".encode(), TEXT_MIME)},
                headers=headers,
            )
        ).json()["id"]
        for n in range(3)
    ]

    response = await client.get("/documents", params={"limit": 2, "offset": 1}, headers=headers)
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 3
    # Newest first overall is [ids[2], ids[1], ids[0]]; the window starts at index 1.
    assert [item["id"] for item in body["items"]] == [ids[1], ids[0]]


async def test_list_rejects_out_of_range_pagination(client: AsyncClient) -> None:
    headers = {"X-Tenant-Id": str(uuid.uuid4())}
    zero_limit = await client.get("/documents", params={"limit": 0}, headers=headers)
    huge_limit = await client.get("/documents", params={"limit": 101}, headers=headers)
    negative_offset = await client.get("/documents", params={"offset": -1}, headers=headers)
    assert zero_limit.status_code == 422
    assert huge_limit.status_code == 422
    assert negative_offset.status_code == 422


async def test_get_document_by_id_scoped_to_tenant(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    created = await client.post(
        "/documents", files={"file": ("get.txt", b"get me", TEXT_MIME)}, headers=headers
    )
    created.raise_for_status()
    document_id = created.json()["id"]

    found = await client.get(f"/documents/{document_id}", headers=headers)
    assert found.status_code == 200
    assert found.json()["id"] == document_id
    assert found.json()["sha256"] == hashlib.sha256(b"get me").hexdigest()

    stranger = await client.get(
        f"/documents/{document_id}", headers={"X-Tenant-Id": str(uuid.uuid4())}
    )
    assert stranger.status_code == 404

    missing = await client.get(f"/documents/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert isinstance(missing.json()["detail"], str)


async def test_download_returns_stored_bytes(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    content = b"%PDF-1.7 amendment bytes"
    created = await client.post(
        "/documents", files={"file": ("msa.pdf", content, PDF_MIME)}, headers=headers
    )

    response = await client.get(f"/documents/{created.json()['id']}/content", headers=headers)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith(PDF_MIME)
    assert 'filename="msa.pdf"' in response.headers["content-disposition"]

    stranger = await client.get(
        f"/documents/{created.json()['id']}/content",
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert stranger.status_code == 404


async def test_delete_removes_row_file_and_is_repeat_safe(
    client: AsyncClient, tmp_path: Path
) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    content = b"delete me"
    created = await client.post(
        "/documents", files={"file": ("gone.txt", content, TEXT_MIME)}, headers=headers
    )
    body = created.json()

    deleted = await client.delete(f"/documents/{body['id']}", headers=headers)
    assert deleted.status_code == 204
    assert not (tmp_path / str(tenant_id) / body["sha256"]).exists()

    assert (await client.get(f"/documents/{body['id']}", headers=headers)).status_code == 404

    repeat = await client.delete(f"/documents/{body['id']}", headers=headers)
    assert repeat.status_code == 404
    assert await document_count() == 0


async def test_declared_type_must_match_actual_bytes(client: AsyncClient) -> None:
    response = await client.post(
        "/documents",
        files={"file": ("fake.txt", b"%PDF-1.7 not really text", TEXT_MIME)},
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 415
    assert "content identified as application/pdf" in response.json()["detail"]
    assert await document_count() == 0


async def test_docx_upload_accepted(client: AsyncClient) -> None:
    response = await upload(client, _docx_bytes(), DOCX_MIME, "amendment.docx")
    assert response.status_code == 201
    assert response.json()["mime_type"] == DOCX_MIME


async def test_upload_with_amends_document_id_links_amendment_to_parent(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    parent = await client.post(
        "/documents", files={"file": ("msa.txt", b"msa v1", TEXT_MIME)}, headers=headers
    )
    parent_id = parent.json()["id"]
    assert parent.json()["amends_document_id"] is None

    amendment = await client.post(
        "/documents",
        files={"file": ("msa-amendment-1.txt", b"msa v2", TEXT_MIME)},
        data={"amends_document_id": parent_id},
        headers=headers,
    )
    assert amendment.status_code == 201
    assert amendment.json()["amends_document_id"] == parent_id

    # Chains are allowed: an amendment may itself be amended.
    second = await client.post(
        "/documents",
        files={"file": ("msa-amendment-2.txt", b"msa v3", TEXT_MIME)},
        data={"amends_document_id": amendment.json()["id"]},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["amends_document_id"] == amendment.json()["id"]

    fetched = await client.get(f"/documents/{amendment.json()['id']}", headers=headers)
    assert fetched.json()["amends_document_id"] == parent_id


async def test_amendment_rejects_unknown_parent_with_404(client: AsyncClient) -> None:
    response = await client.post(
        "/documents",
        files={"file": ("a.txt", b"orphan amendment", TEXT_MIME)},
        data={"amends_document_id": str(uuid.uuid4())},
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    assert await document_count() == 0


async def test_amendment_rejects_parent_from_other_tenant_with_404(
    client: AsyncClient,
) -> None:
    parent = await upload(client, b"other tenant's msa")
    response = await client.post(
        "/documents",
        files={"file": ("a.txt", b"amendment bytes", TEXT_MIME)},
        data={"amends_document_id": parent.json()["id"]},
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    assert await document_count() == 1


async def test_amendment_with_duplicate_bytes_conflicts_even_when_parent_named(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    content = b"msa v1"
    parent = await client.post(
        "/documents", files={"file": ("msa.txt", content, TEXT_MIME)}, headers=headers
    )
    response = await client.post(
        "/documents",
        files={"file": ("amendment.txt", content, TEXT_MIME)},
        data={"amends_document_id": parent.json()["id"]},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["existing_id"] == parent.json()["id"]


async def test_delete_document_with_amendments_conflicts_until_amendments_removed(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    parent = await client.post(
        "/documents", files={"file": ("msa.txt", b"msa v1", TEXT_MIME)}, headers=headers
    )
    amendment = await client.post(
        "/documents",
        files={"file": ("amd.txt", b"msa v2", TEXT_MIME)},
        data={"amends_document_id": parent.json()["id"]},
        headers=headers,
    )

    blocked = await client.delete(f"/documents/{parent.json()['id']}", headers=headers)
    assert blocked.status_code == 409
    still_there = await client.get(f"/documents/{parent.json()['id']}", headers=headers)
    assert still_there.status_code == 200

    removed = await client.delete(f"/documents/{amendment.json()['id']}", headers=headers)
    assert removed.status_code == 204
    freed = await client.delete(f"/documents/{parent.json()['id']}", headers=headers)
    assert freed.status_code == 204
    assert await document_count() == 0


async def test_oversize_upload_rejected_with_413(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    try:
        payload = b"a" * (1024 * 1024 + 1)
        response = await upload(client, payload)
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()
    assert await document_count() == 0
