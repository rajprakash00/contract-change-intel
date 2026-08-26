"""Maps service-layer domain exceptions onto HTTP responses.

Registered once from create_app so routers contain no error-mapping boilerplate:
new endpoints raise domain exceptions and this table decides the wire format.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.schemas.documents import DocumentConflictDetail
from app.services.documents import (
    ALLOWED_MIME_TYPES,
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    MimeNotAllowedError,
    UploadTooLargeError,
)

logger = logging.getLogger(__name__)


def _detail_response(status_code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def _mime_not_allowed(_: Request, exc: MimeNotAllowedError) -> JSONResponse:
    detail = f"{exc}; allowed: {sorted(ALLOWED_MIME_TYPES)}"
    return _detail_response(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail)


async def _upload_too_large(_: Request, exc: UploadTooLargeError) -> JSONResponse:
    detail = f"upload exceeds limit of {exc.max_bytes // (1024 * 1024)} MiB"
    return _detail_response(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail)


async def _document_already_exists(_: Request, exc: DocumentAlreadyExistsError) -> JSONResponse:
    detail = (
        DocumentConflictDetail(existing_id=exc.existing_id).model_dump(mode="json")
        if exc.existing_id is not None
        else str(exc)
    )
    return _detail_response(status.HTTP_409_CONFLICT, detail)


async def _document_not_found(_: Request, exc: DocumentNotFoundError) -> JSONResponse:
    return _detail_response(status.HTTP_404_NOT_FOUND, str(exc))


def register_exception_handlers(app: FastAPI) -> None:
    app.exception_handler(MimeNotAllowedError)(_mime_not_allowed)
    app.exception_handler(UploadTooLargeError)(_upload_too_large)
    app.exception_handler(DocumentAlreadyExistsError)(_document_already_exists)
    app.exception_handler(DocumentNotFoundError)(_document_not_found)
