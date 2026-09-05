"""Maps service-layer domain exceptions onto HTTP responses.

Registered once from create_app so routers contain no error-mapping boilerplate:
new endpoints raise domain exceptions and this table decides the wire format.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.llm.client import LlmCallError, LlmNotConfiguredError, LlmOutputError
from app.schemas.change_report import ChangePrerequisiteDetail
from app.schemas.documents import DocumentConflictDetail
from app.schemas.extraction import DocumentNotParsedDetail
from app.schemas.ingestion import JobConflictDetail
from app.services.change_report import (
    AmendmentMismatchError,
    ChangeReportJobNotFoundError,
    PrerequisiteMissingError,
)
from app.services.documents import (
    ALLOWED_MIME_TYPES,
    DocumentAlreadyExistsError,
    DocumentHasAmendmentsError,
    DocumentNotFoundError,
    MimeNotAllowedError,
    UploadTooLargeError,
)
from app.services.extraction import (
    DocumentNotParsedError,
    ExtractionJobConflictError,
    ExtractionJobNotFoundError,
)
from app.services.ingestion import IngestionJobConflictError, IngestionJobNotFoundError
from app.services.review_queue import ReviewItemAlreadyResolvedError, ReviewItemNotFoundError

logger = logging.getLogger(__name__)


def _detail_response(status_code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def _mime_not_allowed(_: Request, exc: MimeNotAllowedError) -> JSONResponse:
    detail = f"{exc}; allowed: {sorted(ALLOWED_MIME_TYPES)}"
    if exc.sniffed is not None:
        detail += f"; content identified as {exc.sniffed}"
    return _detail_response(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail)


async def _upload_too_large(_: Request, exc: UploadTooLargeError) -> JSONResponse:
    detail = f"upload exceeds limit of {exc.max_bytes // (1024 * 1024)} MiB"
    return _detail_response(status.HTTP_413_CONTENT_TOO_LARGE, detail)


async def _document_already_exists(_: Request, exc: DocumentAlreadyExistsError) -> JSONResponse:
    detail = (
        DocumentConflictDetail(existing_id=exc.existing_id).model_dump(mode="json")
        if exc.existing_id is not None
        else str(exc)
    )
    return _detail_response(status.HTTP_409_CONFLICT, detail)


async def _document_not_found(_: Request, exc: DocumentNotFoundError) -> JSONResponse:
    return _detail_response(status.HTTP_404_NOT_FOUND, str(exc))


async def _document_has_amendments(_: Request, exc: DocumentHasAmendmentsError) -> JSONResponse:
    return _detail_response(status.HTTP_409_CONFLICT, str(exc))


async def _extraction_job_not_found(_: Request, exc: ExtractionJobNotFoundError) -> JSONResponse:
    return _detail_response(status.HTTP_404_NOT_FOUND, str(exc))


async def _ingestion_job_not_found(_: Request, exc: IngestionJobNotFoundError) -> JSONResponse:
    return _detail_response(status.HTTP_404_NOT_FOUND, str(exc))


async def _job_conflict(
    _: Request, exc: ExtractionJobConflictError | IngestionJobConflictError
) -> JSONResponse:
    # Same re-run rule on both job surfaces: 409 while a job is queued/running.
    detail = JobConflictDetail(existing_job_id=exc.job_id).model_dump(mode="json")
    return _detail_response(status.HTTP_409_CONFLICT, detail)


async def _document_not_parsed(_: Request, exc: DocumentNotParsedError) -> JSONResponse:
    # Extraction before a completed ingestion is a caller-sequencing error,
    # not a missing resource: the detail names the ingestion job to run first.
    detail = DocumentNotParsedDetail(ingestion_job_id=exc.ingestion_job_id).model_dump(mode="json")
    return _detail_response(status.HTTP_409_CONFLICT, detail)


async def _change_report_job_not_found(
    _: Request, exc: ChangeReportJobNotFoundError
) -> JSONResponse:
    return _detail_response(status.HTTP_404_NOT_FOUND, str(exc))


async def _amendment_mismatch(_: Request, exc: AmendmentMismatchError) -> JSONResponse:
    return _detail_response(status.HTTP_409_CONFLICT, str(exc))


async def _change_prerequisite_missing(_: Request, exc: PrerequisiteMissingError) -> JSONResponse:
    # Change reports before completed ingestion + extraction on both versions
    # are a caller-sequencing error: the detail names the first missing job.
    detail = ChangePrerequisiteDetail(
        document_id=exc.document_id, kind=exc.kind, job_id=exc.job_id
    ).model_dump(mode="json")
    return _detail_response(status.HTTP_409_CONFLICT, detail)


async def _review_item_not_found(_: Request, exc: ReviewItemNotFoundError) -> JSONResponse:
    return _detail_response(status.HTTP_404_NOT_FOUND, str(exc))


async def _review_item_already_resolved(
    _: Request, exc: ReviewItemAlreadyResolvedError
) -> JSONResponse:
    # The state machine is flat and terminal (W5·A): re-resolving a resolved
    # item is a caller-sequencing error, not a missing resource.
    return _detail_response(status.HTTP_409_CONFLICT, str(exc))


# LlmError has no raising route today (LLM calls live in the worker, not the
# request path); the mapping exists so any future synchronous surface inherits
# the app-wide table instead of inventing per-route handling.
async def _llm_call_error(_: Request, exc: LlmCallError) -> JSONResponse:
    # The model call failed after SDK retries: upstream (OpenAI) is the culprit,
    # not this service — 502, with no internals beyond the model name.
    return _detail_response(status.HTTP_502_BAD_GATEWAY, f"llm call failed model={exc.model}")


async def _llm_output_error(_: Request, exc: LlmOutputError) -> JSONResponse:
    return _detail_response(status.HTTP_502_BAD_GATEWAY, str(exc))


async def _llm_not_configured(_: Request, exc: LlmNotConfiguredError) -> JSONResponse:
    # Missing key is a deployment problem, not a client error: 503, retryable
    # only after the operator fixes the environment.
    return _detail_response(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


def register_exception_handlers(app: FastAPI) -> None:
    app.exception_handler(MimeNotAllowedError)(_mime_not_allowed)
    app.exception_handler(UploadTooLargeError)(_upload_too_large)
    app.exception_handler(DocumentAlreadyExistsError)(_document_already_exists)
    app.exception_handler(DocumentNotFoundError)(_document_not_found)
    app.exception_handler(DocumentHasAmendmentsError)(_document_has_amendments)
    app.exception_handler(ExtractionJobNotFoundError)(_extraction_job_not_found)
    app.exception_handler(IngestionJobNotFoundError)(_ingestion_job_not_found)
    app.exception_handler(ExtractionJobConflictError)(_job_conflict)
    app.exception_handler(IngestionJobConflictError)(_job_conflict)
    app.exception_handler(DocumentNotParsedError)(_document_not_parsed)
    app.exception_handler(ChangeReportJobNotFoundError)(_change_report_job_not_found)
    app.exception_handler(AmendmentMismatchError)(_amendment_mismatch)
    app.exception_handler(PrerequisiteMissingError)(_change_prerequisite_missing)
    app.exception_handler(ReviewItemNotFoundError)(_review_item_not_found)
    app.exception_handler(ReviewItemAlreadyResolvedError)(_review_item_already_resolved)
    app.exception_handler(LlmCallError)(_llm_call_error)
    app.exception_handler(LlmOutputError)(_llm_output_error)
    app.exception_handler(LlmNotConfiguredError)(_llm_not_configured)
