"""
Shared fixtures for all test modules.

The Couchbase SDK is mocked at the db module level so tests run without a
live cluster.  Each fixture exposes a fresh FastAPI TestClient together with
pre-wired mocks for the most common SDK behaviours.
"""
import sys
import os
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient

# Ensure backend/ is importable when pytest is run from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def manager_for(client):
    """Look up the ConnectionManager bound to a TestClient's session cookie."""
    from session_store import session_store, SESSION_COOKIE_NAME

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    return session_store._sessions[session_id]


@pytest.fixture(autouse=True)
def _reset_session_store():
    """Sessions are held in a module-level store; clear it between tests
    so state from one test's sessions never leaks into another's."""
    from session_store import session_store

    session_store._sessions.clear()
    session_store._last_used.clear()
    yield
    session_store._sessions.clear()
    session_store._last_used.clear()


# ---------------------------------------------------------------------------
# Helpers to build lightweight Couchbase SDK fakes
# ---------------------------------------------------------------------------

def _make_bucket_settings(name: str):
    b = MagicMock()
    b.name = name
    return b


def _make_scope(name: str, collections: list[str]):
    scope = MagicMock()
    scope.name = name
    cols = []
    for c in collections:
        col = MagicMock()
        col.name = c
        cols.append(col)
    scope.collections = cols
    return scope


def _make_cluster(
    buckets=("test-bucket",),
    scopes=(("_default", ["_default"]),),
    query_docs=None,
    query_total=1,
):
    """Return a MagicMock that quacks like a couchbase.cluster.Cluster."""
    cluster = MagicMock()

    # wait_until_ready is a no-op
    cluster.wait_until_ready.return_value = None

    # Bucket management
    cluster.buckets.return_value.get_all_buckets.return_value = [
        _make_bucket_settings(b) for b in buckets
    ]

    # Scope / collection listing via bucket().collections().get_all_scopes()
    scope_mocks = [_make_scope(name, cols) for name, cols in scopes]
    cluster.bucket.return_value.collections.return_value.get_all_scopes.return_value = scope_mocks

    # N1QL query — returns count row then data rows
    if query_docs is None:
        query_docs = [{"__cb_key": "doc-1", "summary": "Test memory", "user_id": "u1"}]

    def _side_effect(q, *args, **kwargs):
        if "COUNT(*)" in q:
            return iter([{"total": query_total}])
        if "CREATE INDEX" in q or "CREATE PRIMARY INDEX" in q:
            return iter([])
        return iter(query_docs)

    cluster.query.side_effect = _side_effect

    # Collection KV operations
    kv_col = MagicMock()
    kv_col.upsert.return_value = MagicMock()
    kv_col.remove.return_value = MagicMock()
    cluster.bucket.return_value.scope.return_value.collection.return_value = kv_col

    # Collection-scoped query index manager — report every recommended index
    # as already online so create_recommended_indexes()'s wait loop resolves
    # on its first poll instead of actually sleeping in tests.
    def _all_indexes():
        from db import ConnectionManager

        names = list(ConnectionManager._RECOMMENDED_INDEXES) + [ConnectionManager._PRIMARY_INDEX_NAME]
        return [SimpleNamespace(name=n, state="online") for n in names]

    kv_col.query_indexes.return_value.get_all_indexes.side_effect = _all_indexes

    return cluster


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cluster():
    """A fully-configured cluster mock with one bucket / scope / collection."""
    return _make_cluster(
        buckets=["test-bucket"],
        scopes=[("_default", ["_default"]), ("memories", ["memory"])],
    )


@pytest.fixture
def client(mock_cluster):
    """
    FastAPI TestClient with the Couchbase Cluster constructor patched so that
    connecting automatically returns mock_cluster.
    """
    with patch("db.Cluster", return_value=mock_cluster):
        # Import app *after* the patch is active so db.py sees the mock
        from main import app

        yield TestClient(app)


@pytest.fixture
def connected_client(client, mock_cluster):
    """
    TestClient already connected to the mock cluster with a collection selected.
    """
    resp = client.post("/api/connect", json={
        "connection_string": "couchbase://localhost",
        "username": "Administrator",
        "password": "password",
    })
    assert resp.status_code == 200, resp.text

    client.post("/api/collection", json={
        "bucket": "test-bucket",
        "scope": "_default",
        "collection": "_default",
    })

    return client


@pytest.fixture
def connected_client_with_docs(mock_cluster):
    """
    TestClient connected and pre-loaded with two sample documents.
    """
    docs = [
        {"__cb_key": "mem-abc", "summary": "User prefers dark mode", "user_id": "u1", "type": "preference"},
        {"__cb_key": "mem-xyz", "summary": "User is vegan", "user_id": "u2", "type": "preference"},
    ]
    cluster = _make_cluster(
        buckets=["test-bucket"],
        scopes=[("_default", ["_default"])],
        query_docs=docs,
        query_total=2,
    )

    with patch("db.Cluster", return_value=cluster):
        from main import app

        c = TestClient(app)
        c.post("/api/connect", json={
            "connection_string": "couchbase://localhost",
            "username": "Administrator",
            "password": "password",
        })
        c.post("/api/collection", json={
            "bucket": "test-bucket",
            "scope": "_default",
            "collection": "_default",
        })

        yield c, cluster
