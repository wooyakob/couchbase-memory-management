from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from couchbase.exceptions import DocumentNotFoundException
from typing import Optional
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import UpdateDocumentRequest, BulkDeleteRequest, DocsByIdsRequest
from db import ConnectionManager
from dependencies import SessionContext, get_session

router = APIRouter(prefix="/api/memories", tags=["memories"])
logger = logging.getLogger(__name__)

_INDEX_ERRORS = ("No index available", "no index", "INDEX_NOT_FOUND", "primary_scan")


def _ensure_ready(manager: ConnectionManager):
    if not manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected to Couchbase")
    if not manager.has_collection:
        raise HTTPException(status_code=400, detail="No collection selected")


def _is_index_error(e: Exception) -> bool:
    msg = str(e)
    return any(phrase.lower() in msg.lower() for phrase in _INDEX_ERRORS)


_VALID_TIME_RANGES = {"hour", "day", "week"}


async def _fall_back_to_primary_index(ctx: SessionContext, fn, args: tuple):
    # Last resort: the targeted secondary indexes didn't get created or
    # didn't resolve retrieval (e.g. still building, or the Capella
    # credential can't manage GSIs the way this needs). A primary index
    # satisfies any query, guaranteeing memories stay retrievable.
    try:
        await run_in_threadpool(ctx.manager.create_primary_index)
    except TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="A fallback index is being created and is still coming online — try again shortly.",
        )
    except Exception as primary_err:
        logger.warning("Automatic primary index creation failed: %s", primary_err)
        raise HTTPException(status_code=422, detail="no_index")

    try:
        return await run_in_threadpool(fn, *args)
    except Exception as final_err:
        raise HTTPException(status_code=500, detail=str(final_err))


async def _run_with_index_heal(ctx: SessionContext, fn, *args):
    # Runs a read that needs an index, self-healing if none is usable yet:
    # create the recommended secondary indexes and retry, and only if that
    # still doesn't resolve retrieval fall back to a primary index. The manual
    # "Create Secondary Indexes" button (POST /api/index) stays as a fallback
    # for when this self-heal can't complete (e.g. still building, or the
    # credential can't manage indexes on Capella). Shared by every filtered
    # read so browsing, clustering-input, and group paging heal identically.
    try:
        return await run_in_threadpool(fn, *args)
    except Exception as e:
        if not _is_index_error(e):
            raise HTTPException(status_code=500, detail=str(e))

        logger.warning("Query failed with index-related error, creating recommended indexes: %s", e)
        try:
            await run_in_threadpool(ctx.manager.create_recommended_indexes)
        except TimeoutError:
            raise HTTPException(
                status_code=503,
                detail="Indexes are being created and are still coming online — try again shortly.",
            )
        except Exception as create_err:
            logger.warning("Automatic index creation failed: %s", create_err)
            return await _fall_back_to_primary_index(ctx, fn, args)

        try:
            return await run_in_threadpool(fn, *args)
        except Exception as retry_err:
            if not _is_index_error(retry_err):
                raise HTTPException(status_code=500, detail=str(retry_err))
            logger.warning(
                "Recommended indexes didn't resolve retrieval, falling back to a primary index: %s",
                retry_err,
            )
            return await _fall_back_to_primary_index(ctx, fn, args)


@router.get("")
async def list_memories(
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    time_range: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    ctx: SessionContext = Depends(get_session),
):
    _ensure_ready(ctx.manager)
    if time_range is not None and time_range not in _VALID_TIME_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid time_range '{time_range}'. Must be one of: hour, day, week.",
        )
    return await _run_with_index_heal(
        ctx, ctx.manager.query_documents, search, type, user_id, time_range, limit, offset
    )


@router.get("/cluster-input")
async def cluster_input(
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    time_range: Optional[str] = Query(None),
    max: int = Query(500, ge=1, le=2000),
    ctx: SessionContext = Depends(get_session),
):
    # Lightweight id + primary-text projection for every memory matching the
    # current filter, so "Auto Group" clusters the whole (typically per-user)
    # set instead of just the visible page.
    _ensure_ready(ctx.manager)
    if time_range is not None and time_range not in _VALID_TIME_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid time_range '{time_range}'. Must be one of: hour, day, week.",
        )
    return await _run_with_index_heal(
        ctx, ctx.manager.query_text_for_clustering, search, type, user_id, time_range, max
    )


@router.post("/by-ids")
async def docs_by_ids(req: DocsByIdsRequest, ctx: SessionContext = Depends(get_session)):
    # Fetch full documents for one page's worth of keys — used to browse an AI
    # group whose membership can span more memories than a single browse page.
    _ensure_ready(ctx.manager)
    return await _run_with_index_heal(ctx, ctx.manager.query_documents_by_ids, req.ids)


@router.get("/groups")
async def get_groups(ctx: SessionContext = Depends(get_session)):
    _ensure_ready(ctx.manager)
    try:
        return await run_in_threadpool(ctx.manager.get_groups)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{doc_id:path}")
async def update_memory(doc_id: str, req: UpdateDocumentRequest, ctx: SessionContext = Depends(get_session)):
    _ensure_ready(ctx.manager)
    # Strip synthetic key before saving
    data = {k: v for k, v in req.data.items() if k != "__cb_key"}
    try:
        await run_in_threadpool(ctx.manager.update_document, doc_id, data)
        return {"status": "ok", "doc_id": doc_id}
    except DocumentNotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bulk")
async def bulk_delete(req: BulkDeleteRequest, ctx: SessionContext = Depends(get_session)):
    _ensure_ready(ctx.manager)
    deleted, errors = [], []
    for doc_id in req.doc_ids:
        try:
            await run_in_threadpool(ctx.manager.delete_document, doc_id)
            deleted.append(doc_id)
        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})
    return {"deleted": deleted, "errors": errors}


@router.delete("/{doc_id:path}")
async def delete_memory(doc_id: str, ctx: SessionContext = Depends(get_session)):
    _ensure_ready(ctx.manager)
    try:
        await run_in_threadpool(ctx.manager.delete_document, doc_id)
        return {"status": "ok", "doc_id": doc_id}
    except DocumentNotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
