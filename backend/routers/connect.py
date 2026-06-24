from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from couchbase.exceptions import AuthenticationException, UnAmbiguousTimeoutException

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import ConnectRequest, SelectCollectionRequest
from db import connection_manager

router = APIRouter(prefix="/api", tags=["connection"])


@router.post("/connect")
async def connect(req: ConnectRequest):
    try:
        buckets = await run_in_threadpool(
            connection_manager.connect,
            req.connection_string,
            req.username,
            req.password,
        )
        return {"status": "connected", "buckets": buckets}
    except AuthenticationException:
        raise HTTPException(status_code=401, detail="Authentication failed — check your username and password")
    except UnAmbiguousTimeoutException:
        raise HTTPException(status_code=503, detail="Connection timed out. Check the connection string and ensure the cluster is reachable.")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Connection failed: {str(e)}")


@router.get("/buckets/{bucket}/scopes")
async def list_scopes(bucket: str):
    if not connection_manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    try:
        scopes = await run_in_threadpool(connection_manager.list_scopes, bucket)
        return {"scopes": scopes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buckets/{bucket}/scopes/{scope}/collections")
async def list_collections(bucket: str, scope: str):
    if not connection_manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    try:
        collections = await run_in_threadpool(connection_manager.list_collections, bucket, scope)
        return {"collections": collections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collection")
async def select_collection(req: SelectCollectionRequest):
    if not connection_manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    connection_manager.set_collection(req.bucket, req.scope, req.collection)
    return {"status": "ok", "bucket": req.bucket, "scope": req.scope, "collection": req.collection}


@router.post("/index")
async def create_index():
    if not connection_manager.is_connected:
        raise HTTPException(status_code=400, detail="Not connected")
    try:
        await run_in_threadpool(connection_manager.create_primary_index)
        return {"status": "ok", "message": "Primary index created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/connect")
async def disconnect():
    await run_in_threadpool(connection_manager.disconnect)
    return {"status": "disconnected"}
