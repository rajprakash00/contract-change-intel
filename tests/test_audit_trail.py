"""Audit trail integration: successful mutations leave correlated append-only rows."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

import app.db as db
from app.models.audit_log import AuditLog

TEXT_MIME = "text/plain"


async def tenant_rows(tenant_id: uuid.UUID) -> list[AuditLog]:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
    return list(rows)


async def test_upload_writes_audit_row_correlated_to_request_id(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    response = await client.post(
        "/documents",
        files={"file": ("a.txt", b"audited upload", TEXT_MIME)},
        headers={"X-Tenant-Id": str(tenant_id)},
    )
    assert response.status_code == 201

    rows = await tenant_rows(tenant_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "document.upload"
    assert row.resource_type == "document"
    assert row.resource_id == uuid.UUID(response.json()["id"])
    assert row.request_id == response.headers["x-request-id"]
    assert row.detail["sha256"] == response.json()["sha256"]


async def test_delete_appends_audit_row_after_upload_row(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = {"X-Tenant-Id": str(tenant_id)}
    created = await client.post(
        "/documents",
        files={"file": ("b.txt", b"delete is audited too", TEXT_MIME)},
        headers=headers,
    )
    document_id = created.json()["id"]

    deleted = await client.delete(f"/documents/{document_id}", headers=headers)
    assert deleted.status_code == 204

    rows = await tenant_rows(tenant_id)
    assert [row.action for row in rows] == ["document.upload", "document.delete"]
    assert rows[-1].resource_id == uuid.UUID(document_id)


async def test_rejected_upload_leaves_no_audit_row(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    response = await client.post(
        "/documents",
        files={"file": ("x.exe", b"MZ...", "application/x-msdownload")},
        headers={"X-Tenant-Id": str(tenant_id)},
    )
    assert response.status_code == 415
    assert await tenant_rows(tenant_id) == []
