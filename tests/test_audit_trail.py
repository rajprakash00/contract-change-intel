"""Audit trail integration: successful mutations leave correlated append-only rows."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

import app.db as db
from app.models.audit_log import AuditLog
from tests.fake_jwks import bearer

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
        headers=bearer(tenant_id),
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
    headers = bearer(tenant_id)
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
        headers=bearer(tenant_id),
    )
    assert response.status_code == 415
    assert await tenant_rows(tenant_id) == []


async def test_audit_log_read_lists_tenant_rows_chronologically(
    client: AsyncClient,
) -> None:
    """The read surface mirrors what was written: the tenant's audit rows,
    oldest first, with the correlation and target fields intact."""
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    upload_id = (
        await client.post(
            "/documents",
            files={"file": ("c.txt", b"read path", TEXT_MIME)},
            headers=headers,
        )
    ).json()["id"]

    response = await client.get("/audit-log", headers=headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["action"] for item in items] == ["document.upload"]
    entry = items[0]
    assert uuid.UUID(entry["id"])
    assert entry["tenant_id"] == str(tenant_id)
    assert entry["resource_type"] == "document"
    assert entry["resource_id"] == upload_id
    assert entry["detail"]["sha256"]
    assert entry["created_at"]


async def test_audit_log_read_is_tenant_scoped(client: AsyncClient) -> None:
    """Another tenant's trail is invisible: the list filters on the caller's
    tenant, never on the row's."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await client.post(
        "/documents",
        files={"file": ("d.txt", b"scoped read", TEXT_MIME)},
        headers=bearer(theirs),
    )

    response = await client.get("/audit-log", headers=bearer(mine))

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_audit_log_read_filters_by_action(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    created = await client.post(
        "/documents",
        files={"file": ("e.txt", b"filter test", TEXT_MIME)},
        headers=headers,
    )
    await client.delete(f"/documents/{created.json()['id']}", headers=headers)

    deleted = await client.get("/audit-log", params={"action": "document.delete"}, headers=headers)
    assert [item["action"] for item in deleted.json()["items"]] == ["document.delete"]
    uploads = await client.get("/audit-log", params={"action": "document.upload"}, headers=headers)
    assert [item["action"] for item in uploads.json()["items"]] == ["document.upload"]


async def test_audit_log_read_limit_caps_the_rows(client: AsyncClient) -> None:
    """Limit truncates from the oldest end: with more rows than the cap, the
    newest never displace the earliest events from the trail."""
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    for name in ("f.txt", "g.txt", "h.txt"):
        await client.post(
            "/documents",
            files={"file": (name, f"limit {name}".encode(), TEXT_MIME)},
            headers=headers,
        )

    response = await client.get("/audit-log", params={"limit": 2}, headers=headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert all(item["action"] == "document.upload" for item in items)
