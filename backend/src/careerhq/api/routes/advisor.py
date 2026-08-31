"""The Career Advisor's routes (contracts/advisor-api.md).

Ownership derives from the session — no endpoint accepts a client-supplied
user id — and every path here is picked up by the 401 enumeration the moment
it is registered. The five routes are registered together (T009) and filled in
by their stories: the page read and run lifecycle by US1, the memory/lineage
read by US2, dismissal by US4.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from careerhq.api.deps import CurrentUser, DbSession

router = APIRouter(prefix="/advisor", tags=["advisor"])

_NOT_BUILT = "This part of the advisor is not built yet."


@router.get("", summary="The advisor page's single read")
async def read_advisor(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, summary="Request an analysis")
async def trigger_run(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("/runs/{run_id}", summary="Poll one run")
async def read_run(run_id: str, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("/memories/{memory_id}", summary="One memory with lineage")
async def read_memory(memory_id: str, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.post("/memories/{memory_id}/dismiss", summary="Dismiss a memory")
async def dismiss_memory(memory_id: str, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)
