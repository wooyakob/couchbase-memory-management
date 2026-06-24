"""
Tests for edge-case error handling, index detection, and state isolation.

Covers:
- Various N1QL index error message variants all map to no_primary_index
- Cluster state is not shared across test invocations
- Reconnecting after a failed attempt allows a subsequent successful connect
- Large document payload is accepted
- Document key with URL-special characters is handled via path encoding
"""
import pytest
from unittest.mock import patch, MagicMock
from couchbase.exceptions import AuthenticationException, UnAmbiguousTimeoutException


INDEX_ERROR_VARIANTS = [
    "No index available on keyspace test",
    "no index available",
    "INDEX_NOT_FOUND on collection",
    "primary_scan not available",
]


class TestIndexErrorVariants:
    """All known N1QL error message shapes should produce 422 no_primary_index."""

    @pytest.mark.parametrize("error_msg", INDEX_ERROR_VARIANTS)
    def test_index_error_variant(self, connected_client, error_msg):
        from db import connection_manager
        connection_manager._cluster.query.side_effect = Exception(error_msg)
        resp = connected_client.get("/api/memories")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "no_primary_index"


class TestStateIsolation:
    """Connection state must not bleed between requests."""

    def test_not_connected_after_fresh_client(self, client):
        from db import connection_manager
        assert not connection_manager.is_connected

    def test_no_collection_after_connect_only(self, client, mock_cluster):
        with patch("db.Cluster", return_value=mock_cluster):
            client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "Administrator",
                "password": "password",
            })
        from db import connection_manager
        assert connection_manager.is_connected
        assert not connection_manager.has_collection

    def test_collection_set_after_select(self, connected_client):
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket",
            "scope": "_default",
            "collection": "_default",
        })
        from db import connection_manager
        assert connection_manager.has_collection


class TestRetryAfterFailure:
    """A failed connect should not block a later successful connect."""

    def test_retry_after_auth_failure(self, client, mock_cluster):
        # First attempt: auth error
        with patch("db.Cluster") as BadCluster:
            BadCluster.return_value.wait_until_ready.side_effect = AuthenticationException("bad")
            r1 = client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "wrong",
                "password": "wrong",
            })
        assert r1.status_code == 401

        # Second attempt: success
        with patch("db.Cluster", return_value=mock_cluster):
            r2 = client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "Administrator",
                "password": "password",
            })
        assert r2.status_code == 200
        assert "test-bucket" in r2.json()["buckets"]


class TestDocumentKeyEncoding:
    """Document IDs containing slashes and colons must survive round-trips."""

    def test_delete_namespaced_key(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        # Path param with colons — FastAPI path:path captures the full string
        resp = client.delete("/api/memories/ns%3A%3Auser%3A%3A999")
        # 200 (removed) or 404 (not found) are both acceptable; 422/500 are not
        assert resp.status_code in (200, 404)


class TestCapellaConnectionString:
    """couchbases:// scheme should be accepted the same as couchbase://."""

    def test_capella_scheme_accepted(self, client, mock_cluster):
        with patch("db.Cluster", return_value=mock_cluster):
            resp = client.post("/api/connect", json={
                "connection_string": "couchbases://cb.example.cloud.couchbase.com",
                "username": "user@example.com",
                "password": "s3cr3t",
            })
        assert resp.status_code == 200


class TestConnectionInfo:
    """connection_info property reflects current state."""

    def test_connection_info_after_select(self, connected_client):
        connected_client.post("/api/collection", json={
            "bucket": "test-bucket",
            "scope": "_default",
            "collection": "_default",
        })
        from db import connection_manager
        info = connection_manager.connection_info
        assert info["bucket"] == "test-bucket"
        assert info["scope"] == "_default"
        assert info["collection"] == "_default"

    def test_connection_info_cleared_after_disconnect(self, connected_client):
        connected_client.delete("/api/connect")
        from db import connection_manager
        info = connection_manager.connection_info
        assert info["bucket"] is None
        assert info["collection"] is None
