from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from couchbase.exceptions import DocumentNotFoundException
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import UpdateDocumentRequest, BulkDeleteRequest
from db import connection_manager

router = APIRouter(prefix="/api/memories", tags=["memories"])

_INDEX_ERRORS = ("No index available", "no index", "INDEX_NOT_FOUND", "primary_scan")


def _ensure_ready():
    if not connection_manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected to Couchbase")
    if not connection_manager.has_collection:
        raise HTTPException(status_code=400, detail="No collection selected")


def _is_index_error(e: Exception) -> bool:
    msg = str(e)
    return any(phrase.lower() in msg.lower() for phrase in _INDEX_ERRORS)


_VALID_TIME_RANGES = {"hour", "day", "week"}


@router.get("")
async def list_memories(
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    time_range: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    _ensure_ready()
    if time_range is not None and time_range not in _VALID_TIME_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid time_range '{time_range}'. Must be one of: hour, day, week.",
        )
    try:
        result = await run_in_threadpool(
            connection_manager.query_documents,
            search, type, user_id, time_range, limit, offset,
        )
        return result
    except Exception as e:
        if _is_index_error(e):
            raise HTTPException(
                status_code=422,
                detail="no_primary_index",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups")
async def get_groups():
    _ensure_ready()
    try:
        return await run_in_threadpool(connection_manager.get_groups)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{doc_id:path}")
async def update_memory(doc_id: str, req: UpdateDocumentRequest):
    _ensure_ready()
    # Strip synthetic key before saving
    data = {k: v for k, v in req.data.items() if k != "__cb_key"}
    try:
        await run_in_threadpool(connection_manager.update_document, doc_id, data)
        return {"status": "ok", "doc_id": doc_id}
    except DocumentNotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bulk")
async def bulk_delete(req: BulkDeleteRequest):
    _ensure_ready()
    deleted, errors = [], []
    for doc_id in req.doc_ids:
        try:
            await run_in_threadpool(connection_manager.delete_document, doc_id)
            deleted.append(doc_id)
        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})
    return {"deleted": deleted, "errors": errors}


@router.delete("/{doc_id:path}")
async def delete_memory(doc_id: str):
    _ensure_ready()
    try:
        await run_in_threadpool(connection_manager.delete_document, doc_id)
        return {"status": "ok", "doc_id": doc_id}
    except DocumentNotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
