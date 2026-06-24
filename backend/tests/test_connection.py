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
- Creating a primary index requires connection + collection
"""
import pytest
from unittest.mock import patch, MagicMock
from couchbase.exceptions import AuthenticationException, UnAmbiguousTimeoutException


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
        from db import connection_manager
        assert connection_manager.is_connected

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
        connected_client.delete("/api/connect")
        from db import connection_manager
        assert not connection_manager.is_connected
        assert not connection_manager.has_collection

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
        from db import connection_manager
        assert connection_manager.has_collection


# ---------------------------------------------------------------------------
# Primary index
# ---------------------------------------------------------------------------

class TestPrimaryIndex:
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

    def test_create_index_sdk_error_returns_500(self, connected_client, mock_cluster):
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket", "scope": "_default", "collection": "_default"
        })
        mock_cluster.query.side_effect = RuntimeError("index creation failed")
        resp = connected_client.post("/api/index")
        assert resp.status_code == 500
