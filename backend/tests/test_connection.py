"""
Tests for cluster connection, disconnection, and collection selection.

Covers:
- Successful connect returns bucket list
- Authentication failure (401)
- Timeout / unreachable host (503)
- Generic connection error (503)
- Disconnect clears state
- Listing scopes requires an active connection
- Listing collections requires an active connection
- Selecting a collection sets active path
- Creating secondary indexes requires connection + collection
"""
import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from couchbase.exceptions import AuthenticationException, UnAmbiguousTimeoutException

from tests.conftest import manager_for


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_success_returns_buckets(self, client, mock_cluster):
        resp = client.post("/api/connect", json={
            "connection_string": "couchbase://localhost",
            "username": "Administrator",
            "password": "password",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "connected"
        assert "test-bucket" in body["buckets"]

    def test_connect_stores_connection_string(self, client, mock_cluster):
        client.post("/api/connect", json={
            "connection_string": "couchbase://localhost",
            "username": "Administrator",
            "password": "password",
        })
        assert manager_for(client).is_connected

    def test_connect_auth_failure_returns_401(self, client):
        with patch("db.Cluster") as MockCluster:
            MockCluster.return_value.wait_until_ready.side_effect = AuthenticationException("bad creds")
            resp = client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "wrong",
                "password": "wrong",
            })
        assert resp.status_code == 401
        assert "Authentication failed" in resp.json()["detail"]

    def test_connect_timeout_returns_503(self, client):
        with patch("db.Cluster") as MockCluster:
            MockCluster.return_value.wait_until_ready.side_effect = UnAmbiguousTimeoutException("timed out")
            resp = client.post("/api/connect", json={
                "connection_string": "couchbase://does-not-exist",
                "username": "Administrator",
                "password": "password",
            })
        assert resp.status_code == 503
        assert "timed out" in resp.json()["detail"].lower() or "Connection" in resp.json()["detail"]

    def test_connect_generic_error_returns_503(self, client):
        with patch("db.Cluster") as MockCluster:
            MockCluster.side_effect = RuntimeError("network unreachable")
            resp = client.post("/api/connect", json={
                "connection_string": "couchbase://bad-host",
                "username": "Administrator",
                "password": "password",
            })
        assert resp.status_code == 503
        assert "Connection failed" in resp.json()["detail"]

    def test_connect_missing_fields_returns_422(self, client):
        resp = client.post("/api/connect", json={"connection_string": "couchbase://localhost"})
        assert resp.status_code == 422

    def test_reconnect_replaces_existing_cluster(self, client, mock_cluster):
        """A second connect call should succeed and update the cluster."""
        for _ in range(2):
            resp = client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "Administrator",
                "password": "password",
            })
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_returns_disconnected(self, connected_client):
        resp = connected_client.delete("/api/connect")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    def test_disconnect_clears_state(self, connected_client):
        session_id = connected_client.cookies.get("mm_session_id")
        connected_client.delete("/api/connect")
        from session_store import session_store
        assert session_id not in session_store._sessions

    def test_disconnect_when_not_connected_still_returns_200(self, client):
        resp = client.delete("/api/connect")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scopes and collections
# ---------------------------------------------------------------------------

class TestScopesAndCollections:
    def test_list_scopes_requires_connection(self, client):
        resp = client.get("/api/buckets/test-bucket/scopes")
        assert resp.status_code == 400
        assert "Not connected" in resp.json()["detail"]

    def test_list_scopes_success(self, connected_client):
        resp = connected_client.get("/api/buckets/test-bucket/scopes")
        assert resp.status_code == 200
        body = resp.json()
        assert "scopes" in body
        assert isinstance(body["scopes"], list)
        assert len(body["scopes"]) > 0

    def test_list_scopes_filters_system_scope(self, connected_client):
        # _system should NOT be returned by the endpoint (filtered in UI, not backend)
        resp = connected_client.get("/api/buckets/test-bucket/scopes")
        assert resp.status_code == 200

    def test_list_collections_requires_connection(self, client):
        resp = client.get("/api/buckets/test-bucket/scopes/_default/collections")
        assert resp.status_code == 400

    def test_list_collections_success(self, connected_client):
        resp = connected_client.get("/api/buckets/test-bucket/scopes/_default/collections")
        assert resp.status_code == 200
        assert "collections" in resp.json()

    def test_list_collections_unknown_scope_returns_empty(self, connected_client):
        resp = connected_client.get("/api/buckets/test-bucket/scopes/no-such-scope/collections")
        assert resp.status_code == 200
        assert resp.json()["collections"] == []


# ---------------------------------------------------------------------------
# Select collection
# ---------------------------------------------------------------------------

class TestSelectCollection:
    def test_select_collection_requires_connection(self, client):
        resp = client.post("/api/collection", json={
            "bucket": "b", "scope": "s", "collection": "c"
        })
        assert resp.status_code == 400

    def test_select_collection_success(self, connected_client):
        resp = connected_client.post("/api/collection", json={
            "bucket": "test-bucket",
            "scope": "_default",
            "collection": "_default",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["bucket"] == "test-bucket"
        assert body["scope"] == "_default"
        assert body["collection"] == "_default"

    def test_select_collection_sets_has_collection(self, connected_client):
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket",
            "scope": "_default",
            "collection": "_default",
        })
        assert manager_for(connected_client).has_collection


# ---------------------------------------------------------------------------
# Secondary indexes
# ---------------------------------------------------------------------------

class TestSecondaryIndexes:
    def test_create_index_requires_connection(self, client):
        resp = client.post("/api/index")
        assert resp.status_code == 400

    def test_create_index_success(self, connected_client, mock_cluster):
        # Ensure collection is selected
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket", "scope": "_default", "collection": "_default"
        })
        resp = connected_client.post("/api/index")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert set(resp.json()["indexes"]) == {
            "idx_mm_docid", "idx_mm_type", "idx_mm_user_id", "idx_mm_created_at", "idx_mm_block_id",
        }

    def test_create_index_sdk_error_returns_500(self, connected_client, mock_cluster):
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket", "scope": "_default", "collection": "_default"
        })
        mock_cluster.query.side_effect = RuntimeError("index creation failed")
        resp = connected_client.post("/api/index")
        assert resp.status_code == 500

    def test_create_index_tolerates_capella_visibility_lag(self, connected_client, mock_cluster):
        """On Capella a freshly created index can briefly raise
        QueryIndexNotFoundException from a collection-scoped lookup before
        it's visible — that must be tolerated as "not online yet", not
        treated as a fatal error."""
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket", "scope": "_default", "collection": "_default"
        })
        index_mgr = mock_cluster.bucket.return_value.scope.return_value.collection.return_value.query_indexes.return_value
        calls = {"n": 0}

        def flaky_get_all_indexes():
            calls["n"] += 1
            if calls["n"] == 1:
                from couchbase.exceptions import QueryIndexNotFoundException
                raise QueryIndexNotFoundException("index not visible yet")
            from db import ConnectionManager
            return [SimpleNamespace(name=n, state="online") for n in ConnectionManager._RECOMMENDED_INDEXES]

        index_mgr.get_all_indexes.side_effect = flaky_get_all_indexes

        resp = connected_client.post("/api/index")
        assert resp.status_code == 200
        assert calls["n"] >= 2

    def test_create_index_actually_submits_ddl_statements(self, connected_client, mock_cluster):
        """The Couchbase SDK's QueryResult is lazy — nothing is sent to the
        server until the result is iterated (or .execute() is called).
        Calling cluster.query(stmt) and discarding the return value would
        silently never create the index against a real cluster, even though
        a MagicMock's side_effect (which fires on call, not on iteration)
        can't catch that. Simulate real laziness and assert the DDL is
        actually consumed."""
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket", "scope": "_default", "collection": "_default"
        })

        class LazyResult:
            def __init__(self, on_consume):
                self._on_consume = on_consume

            def __iter__(self):
                self._on_consume()
                return iter([])

        consumed = []

        def lazy_query(q, *args, **kwargs):
            if "CREATE INDEX" in q or "CREATE PRIMARY INDEX" in q:
                return LazyResult(lambda: consumed.append(q))
            return iter([])

        mock_cluster.query.side_effect = lazy_query

        resp = connected_client.post("/api/index")
        assert resp.status_code == 200
        assert len(consumed) == 5

    def test_create_index_surfaces_real_polling_errors_immediately(self, connected_client, mock_cluster):
        """A real failure while polling index state (e.g. a Capella
        credential that can create but not list indexes) must surface
        immediately as its own error, not be swallowed into a misleading
        504 timeout after the full wait."""
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket", "scope": "_default", "collection": "_default"
        })
        index_mgr = mock_cluster.bucket.return_value.scope.return_value.collection.return_value.query_indexes.return_value
        index_mgr.get_all_indexes.side_effect = RuntimeError(
            "User does not have credentials to run GET_ALL_INDEXES"
        )

        resp = connected_client.post("/api/index")
        assert resp.status_code == 500
        assert "credentials" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Session isolation — regression test for the global-singleton bug
# ---------------------------------------------------------------------------

class TestSessionIsolation:
    """Two concurrent 'users' (separate TestClients, no shared cookie jar)
    must never see each other's cluster/collection state."""

    def test_separate_clients_get_separate_managers(self):
        from fastapi.testclient import TestClient
        from tests.conftest import _make_cluster

        cluster_a = _make_cluster(buckets=["bucket-a"], scopes=[("_default", ["_default"])])
        cluster_b = _make_cluster(buckets=["bucket-b"], scopes=[("_default", ["other-col"])])

        from main import app

        with patch("db.Cluster", return_value=cluster_a):
            client_a = TestClient(app)
            client_a.post("/api/connect", json={
                "connection_string": "couchbase://host-a",
                "username": "a", "password": "a",
            })
            client_a.post("/api/collection", json={
                "bucket": "bucket-a", "scope": "_default", "collection": "_default",
            })

        with patch("db.Cluster", return_value=cluster_b):
            client_b = TestClient(app)
            client_b.post("/api/connect", json={
                "connection_string": "couchbase://host-b",
                "username": "b", "password": "b",
            })
            client_b.post("/api/collection", json={
                "bucket": "bucket-b", "scope": "_default", "collection": "other-col",
            })

        manager_a = manager_for(client_a)
        manager_b = manager_for(client_b)

        assert manager_a is not manager_b

        info_a = manager_a.connection_info
        info_b = manager_b.connection_info
        assert info_a["bucket"] == "bucket-a"
        assert info_a["collection"] == "_default"
        assert info_b["bucket"] == "bucket-b"
        assert info_b["collection"] == "other-col"

        # Client A's state must be untouched by client B's later calls.
        assert manager_for(client_a).connection_info["bucket"] == "bucket-a"
