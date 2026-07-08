# Couchbase Memory Management

A browser-based dashboard for viewing, searching, grouping and deleting agent memory documents stored in Couchbase. Connects to self-managed Couchbase Server (`couchbase://`) or Couchbase Capella (`couchbases://`).

This is a **read, organise and delete management layer** — it does not write or edit memories. Editing is intentionally disabled: modifying a memory after creation risks inconsistent data and would require re-vectorisation to preserve semantic search accuracy.

---

## Features

- **Browse & search** memories across any bucket / scope / collection
- **Group** by `type`, `user_id`, or AI-generated themes
- **View** full document content and Couchbase metadata in a tabbed detail panel
- **Delete** single or bulk documents with a mandatory confirmation step
- **AI Auto-cluster** — groups memories into themes using Claude, OpenAI, or Gemini

---

## Quick start (local)

```bash
./start.sh
```

Opens:
- Backend API — http://localhost:8010
- Frontend — http://localhost:5183

### Manual start

```bash
# Backend
cd backend && ../backend/venv/bin/uvicorn main:app --reload --port 8010

# Frontend (separate terminal)
cd frontend && npm run dev
```

### Install dependencies

```bash
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

---

## Quick start (Docker)

```bash
# Pull and run from Docker Hub
docker run -p 8010:8000 wooyakob/memory-manager:latest

# Or build and run locally
docker compose up --build
```

Opens at http://localhost:8010 — the backend serves the built frontend.

---

## Connecting

1. Enter your Couchbase connection string, username, and password
2. Select a bucket → scope → collection
3. If prompted, create the recommended secondary indexes (required for N1QL queries) — these cover `type`, `user_id`, `created_at`, and `block_id` for filtered browsing, plus a keys-only index on the document ID for unfiltered browsing/pagination. Primary indexes aren't created since they aren't recommended for production use.

> **Connecting to a Couchbase Server running on your own machine?** The right host depends on how the *backend* itself is running, not how you start it in general:
> - **Backend running via `./start.sh`** (a plain process on your machine, not containerized) → use `localhost`. `host.docker.internal` doesn't resolve here — nothing is putting the backend inside a Docker network.
>   ```
>   couchbase://localhost
>   ```
> - **Backend running via `docker run` / `docker compose`** (the backend itself is inside a container) → use `host.docker.internal`, since `localhost` from inside that container refers to the container, not your machine.
>   ```
>   couchbase://host.docker.internal
>   ```

### Example (agentmem on Couchbase Server)

| Field | Value |
|-------|-------|
| Connection string | `couchbase://localhost` (`./start.sh`) or `couchbase://host.docker.internal` (Docker) — see note above |
| Bucket | `agentmems` |
| Scope | `agentmem` |
| Collection | `memory` |

---

## Document detail panel

Clicking a memory card opens a two-tab panel:

**Document tab** — all non-embedding document fields rendered as text, arrays, or JSON.

**Metadata tab** — Couchbase document metadata returned via `META()`:

| Field | Description |
|-------|-------------|
| Document Key | The Couchbase document ID |
| CAS | Compare-and-Swap value used for optimistic concurrency |
| Expiry | TTL expiration timestamp (or "None" if the document never expires) |
| Document Type | Typically `json` |
| Field Count | Number of visible document fields |
| Embedding | Which fields contain vector embeddings and their dimensionality |

---

## Deletion

Every deletion requires explicit confirmation in a modal dialog. Confirmed deletions are permanent and cannot be undone. Deleting stale or inaccurate memories prevents agents from using them to produce incorrect responses.

---

## Supported document schemas

The dashboard auto-detects the primary text field in this order: `summary → content → fact → text → message.user_content`.

JSON structures for memories are displayed. Embedding fields are detected and excluded from the document view (shown only in the Metadata tab).

---

## Architecture

```
backend/          Python FastAPI, port 8010
  main.py         App + CORS + static SPA serving
  db.py           ConnectionManager — Couchbase SDK 4.x, N1QL + META() queries
  models.py       Pydantic request models
  routers/
    connect.py    Cluster connect/disconnect, bucket/scope/collection listing
    memories.py   List (paginated), delete single/bulk
  tests/
    conftest.py          Fixtures and mock cluster factory
    test_connection.py   Connection, disconnect, scopes, collections, index
    test_memories.py     List, groups, delete, bulk delete
    test_errors.py       Error variants, state isolation, retry after failure

frontend/         React 18 + Vite 5, port 5183
  src/
    api.js        Fetch wrapper for all /api/* calls
    App.jsx       Root — ConnectionScreen vs MemoryDashboard
    components/
      ConnectionScreen.jsx   Two-step credentials + collection selector
      MemoryDashboard.jsx    Dashboard: sidebar, cards, tabbed detail panel
```

Vite proxies `/api/*` → `localhost:8010` in development. In production (and Docker), FastAPI serves the built frontend from `frontend/dist/`.

---

## Running tests

```bash

# Install test dependencies
backend/venv/bin/pip install pytest httpx

# Run all tests
backend/venv/bin/pytest backend/tests/ -v
```

Tests mock the Couchbase SDK — no live cluster required.
