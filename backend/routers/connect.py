from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from couchbase.exceptions import AuthenticationException, UnAmbiguousTimeoutException
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import ConnectRequest, SelectCollectionRequest
from dependencies import SessionContext, get_session
from session_store import session_store, SESSION_COOKIE_NAME

router = APIRouter(prefix="/api", tags=["connection"])
logger = logging.getLogger(__name__)


@router.post("/connect")
async def connect(req: ConnectRequest, ctx: SessionContext = Depends(get_session)):
    try:
        buckets = await run_in_threadpool(
            ctx.manager.connect,
            req.connection_string,
            req.username,
            req.password,
        )
        return {"status": "connected", "buckets": buckets}
    except AuthenticationException:
        raise HTTPException(status_code=401, detail="Authentication failed — check your username and password")
    except UnAmbiguousTimeoutException as e:
        logger.warning("Connect timed out: %s", e)
        raise HTTPException(status_code=503, detail="Connection timed out. Check the connection string and ensure the cluster is reachable.")
    except Exception as e:
        logger.warning("Connect failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Connection failed: {str(e)}")


@router.get("/buckets/{bucket}/scopes")
async def list_scopes(bucket: str, ctx: SessionContext = Depends(get_session)):
    if not ctx.manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    try:
        scopes = await run_in_threadpool(ctx.manager.list_scopes, bucket)
        return {"scopes": scopes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buckets/{bucket}/scopes/{scope}/collections")
async def list_collections(bucket: str, scope: str, ctx: SessionContext = Depends(get_session)):
    if not ctx.manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    try:
        collections = await run_in_threadpool(ctx.manager.list_collections, bucket, scope)
        return {"collections": collections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collection")
async def select_collection(req: SelectCollectionRequest, ctx: SessionContext = Depends(get_session)):
    if not ctx.manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    ctx.manager.set_collection(req.bucket, req.scope, req.collection)
    return {"status": "ok", "bucket": req.bucket, "scope": req.scope, "collection": req.collection}


@router.post("/index")
async def create_index(ctx: SessionContext = Depends(get_session)):
    if not ctx.manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    try:
        created = await run_in_threadpool(ctx.manager.create_recommended_indexes)
        return {"status": "ok", "message": "Secondary indexes created successfully", "indexes": created}
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Indexes were created but did not come online in time. The indexer may still be building them — wait a moment and retry.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/connect")
async def disconnect(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        await run_in_threadpool(session_store.drop, session_id)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "disconnected"}
