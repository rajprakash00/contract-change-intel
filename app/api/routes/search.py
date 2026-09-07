"""HTTP adapter for search: parse request, call service, return schema.

GET /search is the synchronous hybrid-search surface (ADR-006): the query is
embedded in the request path (503 when the key is missing, 502 when the embed
call fails — mapped by the app-wide error table), then fused results come
back as citation-spanned hits. Top-k only; no pagination.
"""

from typing import Annotated

from fastapi import APIRouter, Query

import app.services.search as search_service
from app.api.deps import LlmClientDep, PrincipalDep, SessionDep
from app.schemas.search import SearchHitRead, SearchResponse

router = APIRouter(tags=["search"])

# Eval metrics report recall@5 and recall@10, so the default sits at 10 and
# the cap stays generous enough for any downstream impact-mapping fetch.
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


@router.get("/search", response_model=SearchResponse)
async def get_search(
    session: SessionDep,
    llm: LlmClientDep,
    principal: PrincipalDep,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
) -> SearchResponse:
    hits = await search_service.search(
        session, llm=llm, tenant_id=principal.tenant_id, query=q, limit=limit
    )
    return SearchResponse(items=[SearchHitRead.model_validate(hit) for hit in hits])
