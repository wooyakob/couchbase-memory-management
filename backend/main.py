import os
import sys
from contextlib import asynccontextmanager

# Ensure the backend directory is on sys.path so routers can import db/models
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers import connect, memories, cluster
from session_store import session_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for manager in session_store.all_managers():
        manager.disconnect()


app = FastAPI(title="Couchbase Memory Management", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connect.router)
app.include_router(memories.router)
app.include_router(cluster.router)

# Serve built frontend in production
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Serve static files from dist root (favicon, images, etc.) if they exist
        if full_path:
            static_file = os.path.join(FRONTEND_DIST, full_path)
            if os.path.isfile(static_file):
                return FileResponse(static_file)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
