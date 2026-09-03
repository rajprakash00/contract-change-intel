"""HTTP adapter for document endpoints: parse request, call service, return schema.

No business rules and no error mapping here — validation and orchestration live
in services; domain exceptions become HTTP responses via app.errors handlers.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

import app.services.documents as documents_service
from app.api.deps import SessionDep, SettingsDep, TenantId
from app.schemas.documents import DocumentConflictDetail, DocumentListPage, DocumentRead

router = APIRouter(tags=["documents"])

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"description": "no such document for this tenant"}
}


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentRead,
    responses={
        404: {"description": "amends_document_id names no document in this tenant"},
        409: {
            "model": DocumentConflictDetail,
            "description": "duplicate content in tenant",
        },
        413: {"description": "upload exceeds size limit"},
        415: {"description": "mime type not allowed"},
    },
)
async def post_documents(
    session: SessionDep,
    settings: SettingsDep,
    file: UploadFile,
    tenant_id: TenantId,
    amends_document_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentRead:
    document = await documents_service.upload_document(
        session,
        tenant_id=tenant_id,
        filename=file.filename,
        content_type=file.content_type,
        read=file.read,
        data_dir=settings.data_dir,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        amends_document_id=amends_document_id,
    )
    return DocumentRead.model_validate(document)


@router.get("/documents", response_model=DocumentListPage)
async def get_documents(
    session: SessionDep,
    tenant_id: TenantId,
    limit: Annotated[int, Query(ge=1, le=documents_service.MAX_LIST_LIMIT)] = (
        documents_service.DEFAULT_LIST_LIMIT
    ),
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListPage:
    items, total = await documents_service.list_documents(
        session, tenant_id=tenant_id, limit=limit, offset=offset
    )
    return DocumentListPage(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def get_document(
    session: SessionDep,
    document_id: uuid.UUID,
    tenant_id: TenantId,
) -> DocumentRead:
    document = await documents_service.get_document(
        session, tenant_id=tenant_id, document_id=document_id
    )
    return DocumentRead.model_validate(document)


@router.get(
    "/documents/{document_id}/content",
    response_class=FileResponse,
    responses=_NOT_FOUND_RESPONSE,
)
async def get_document_content(
    session: SessionDep,
    document_id: uuid.UUID,
    tenant_id: TenantId,
    settings: SettingsDep,
) -> FileResponse:
    document, path = await documents_service.resolve_document_file(
        session, tenant_id=tenant_id, document_id=document_id, data_dir=settings.data_dir
    )
    return FileResponse(path=str(path), media_type=document.mime_type, filename=document.filename)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "no such document for this tenant"},
        409: {"description": "document still has amendments"},
    },
)
async def delete_document(
    session: SessionDep,
    document_id: uuid.UUID,
    tenant_id: TenantId,
    settings: SettingsDep,
) -> None:
    await documents_service.delete_document(
        session, tenant_id=tenant_id, document_id=document_id, data_dir=settings.data_dir
    )
