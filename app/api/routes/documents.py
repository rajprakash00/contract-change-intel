"""HTTP adapter for document endpoints: parse request, call service, return schema.

No business rules and no error mapping here — validation and orchestration live
in services; domain exceptions become HTTP responses via app.errors handlers.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, UploadFile, status

import app.services.documents as documents_service
from app.api.deps import SessionDep, SettingsDep
from app.schemas.documents import DocumentConflictDetail, DocumentRead

router = APIRouter(tags=["documents"])


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentRead,
    responses={
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
    tenant_id: Annotated[uuid.UUID, Header(alias="X-Tenant-Id")],
) -> DocumentRead:
    document = await documents_service.upload_document(
        session,
        tenant_id=tenant_id,
        filename=file.filename,
        content_type=file.content_type,
        read=file.read,
        data_dir=settings.data_dir,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
    )
    return DocumentRead.model_validate(document)
