"""
Shared fixtures for all test modules.

The Couchbase SDK is mocked at the db module level so tests run without a
live cluster.  Each fixture exposes a fresh FastAPI TestClient together with
pre-wired mocks for the most common SDK behaviours.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient

# Ensure backend/ is importable when pytest is run from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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
        if "CREATE PRIMARY INDEX" in q:
            return iter([])
        return iter(query_docs)

    cluster.query.side_effect = _side_effect

    # Collection KV operations
    kv_col = MagicMock()
    kv_col.upsert.return_value = MagicMock()
    kv_col.remove.return_value = MagicMock()
    cluster.bucket.return_value.scope.return_value.collection.return_value = kv_col

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
        from db import connection_manager

        # Reset singleton state between tests
        connection_manager._cluster = None
        connection_manager._bucket_name = None
        connection_manager._scope_name = None
        connection_manager._collection_name = None

        yield TestClient(app)

        # Cleanup
        connection_manager._cluster = None
        connection_manager._bucket_name = None
        connection_manager._scope_name = None
        connection_manager._collection_name = None


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
        from db import connection_manager

        connection_manager._cluster = None
        connection_manager._bucket_name = None
        connection_manager._scope_name = None
        connection_manager._collection_name = None

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

        connection_manager._cluster = None
        connection_manager._bucket_name = None
        connection_manager._scope_name = None
        connection_manager._collection_name = None
