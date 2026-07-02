"""
Tests for memory listing, group queries, and deletion.

Covers:
- Listing requires connection + collection
- Listing returns paginated documents
- Listing with search filter passes it through
- Listing with type / user_id filter passes it through
- No-index error triggers automatic index creation + retry
- Automatic index creation still-building/failure fall back to 503 / 422 "no_index"
- Group query returns type and user_id groups
- Delete single document
- Delete document not found returns 404
- Delete propagates SDK errors as 500
- Bulk delete removes multiple documents
- Bulk delete partial failure reports errors per document
"""
import pytest
from unittest.mock import MagicMock, patch, call
from couchbase.exceptions import DocumentNotFoundException

from tests.conftest import manager_for


# ---------------------------------------------------------------------------
# List memories
# ---------------------------------------------------------------------------

class TestListMemories:
    def test_list_requires_connection(self, client):
        resp = client.get("/api/memories")
        assert resp.status_code == 400

    def test_list_requires_collection(self, client, mock_cluster):
        with patch("db.Cluster", return_value=mock_cluster):
            client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "Administrator",
                "password": "password",
            })
        # No collection selected yet
        resp = client.get("/api/memories")
        assert resp.status_code == 400
        assert "collection" in resp.json()["detail"].lower()

    def test_list_returns_documents_and_total(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.get("/api/memories")
        assert resp.status_code == 200
        body = resp.json()
        assert "documents" in body
        assert "total" in body
        assert body["total"] == 2
        assert len(body["documents"]) == 2

    def test_list_includes_meta_fields(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.get("/api/memories")
        docs = resp.json()["documents"]
        first = docs[0]
        assert "__cb_key" in first

    def test_list_default_pagination(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.get("/api/memories?limit=50&offset=0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_list_custom_pagination(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.get("/api/memories?limit=10&offset=5")
        assert resp.status_code == 200

    def test_list_with_search_passes_param(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        resp = client.get("/api/memories?search=dark+mode")
        assert resp.status_code == 200
        # Verify the query included the search term
        calls = cluster.query.call_args_list
        query_strings = [str(c) for c in calls]
        assert any("search" in q or "dark" in q.lower() for q in query_strings)

    def test_list_with_type_filter(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        resp = client.get("/api/memories?type=preference")
        assert resp.status_code == 200

    def test_list_with_user_id_filter(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        resp = client.get("/api/memories?user_id=u1")
        assert resp.status_code == 200

    def test_list_no_index_returns_422(self, connected_client):
        manager_for(connected_client)._cluster.query.side_effect = Exception(
            "No index available on keyspace - INDEX_NOT_FOUND"
        )
        resp = connected_client.get("/api/memories")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "no_index"

    def test_list_auto_creates_index_and_retries(self, connected_client_with_docs):
        """The first query hits a missing index — instead of just reporting
        the error, list_memories should create the recommended indexes
        itself and retry, returning the actual memories."""
        client, cluster = connected_client_with_docs
        base_side_effect = cluster.query.side_effect
        state = {"failed_once": False}

        def flaky(q, *args, **kwargs):
            if "COUNT(*)" in q and not state["failed_once"]:
                state["failed_once"] = True
                raise Exception("No index available on keyspace - INDEX_NOT_FOUND")
            return base_side_effect(q, *args, **kwargs)

        cluster.query.side_effect = flaky

        resp = client.get("/api/memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["documents"]) == 2

        create_calls = [c for c in cluster.query.call_args_list if "CREATE INDEX" in str(c)]
        assert len(create_calls) == 5

    def test_list_index_still_building_returns_503(self, connected_client_with_docs):
        """If the auto-created indexes haven't come online yet, report a
        retryable 503 rather than a dead-end error."""
        client, cluster = connected_client_with_docs
        manager = manager_for(client)
        cluster.query.side_effect = Exception("No index available on keyspace - INDEX_NOT_FOUND")

        with patch.object(manager, "create_recommended_indexes", side_effect=TimeoutError("still building")):
            resp = client.get("/api/memories")

        assert resp.status_code == 503

    def test_list_auto_create_failure_falls_back_to_no_index(self, connected_client_with_docs):
        """If the auto-heal attempt itself fails outright (not a timeout),
        fall back to the manual-recovery 422 the frontend already knows
        how to handle."""
        client, cluster = connected_client_with_docs
        manager = manager_for(client)
        cluster.query.side_effect = Exception("No index available on keyspace - INDEX_NOT_FOUND")

        with patch.object(manager, "create_recommended_indexes", side_effect=RuntimeError("no privileges")):
            resp = client.get("/api/memories")

        assert resp.status_code == 422
        assert resp.json()["detail"] == "no_index"

    def test_list_falls_back_to_primary_index_when_secondary_retry_still_fails(self, connected_client_with_docs):
        """If the recommended secondary indexes were created but the retried
        query still hits an index error (e.g. not fully online yet on
        Capella), fall back to a primary index and retry once more instead
        of dead-ending in a 422."""
        client, cluster = connected_client_with_docs
        manager = manager_for(client)
        base_side_effect = cluster.query.side_effect
        state = {"calls": 0}

        def flaky(q, *args, **kwargs):
            if "COUNT(*)" in q:
                state["calls"] += 1
                if state["calls"] <= 2:
                    raise Exception("No index available on keyspace - INDEX_NOT_FOUND")
            return base_side_effect(q, *args, **kwargs)

        cluster.query.side_effect = flaky

        with patch.object(manager, "create_recommended_indexes", return_value=list(manager._RECOMMENDED_INDEXES)):
            resp = client.get("/api/memories")

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_primary_index_fallback_still_building_returns_503(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        manager = manager_for(client)
        cluster.query.side_effect = Exception("No index available on keyspace - INDEX_NOT_FOUND")

        with patch.object(manager, "create_recommended_indexes", side_effect=RuntimeError("no privileges")), \
             patch.object(manager, "create_primary_index", side_effect=TimeoutError("still building")):
            resp = client.get("/api/memories")

        assert resp.status_code == 503

    def test_list_primary_index_fallback_failure_returns_no_index(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        manager = manager_for(client)
        cluster.query.side_effect = Exception("No index available on keyspace - INDEX_NOT_FOUND")

        with patch.object(manager, "create_recommended_indexes", side_effect=RuntimeError("no privileges")), \
             patch.object(manager, "create_primary_index", side_effect=RuntimeError("still no privileges")):
            resp = client.get("/api/memories")

        assert resp.status_code == 422
        assert resp.json()["detail"] == "no_index"

    def test_list_sdk_error_returns_500(self, connected_client):
        manager_for(connected_client)._cluster.query.side_effect = RuntimeError("cluster error")
        resp = connected_client.get("/api/memories")
        assert resp.status_code == 500

    def test_list_limit_capped_at_200(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.get("/api/memories?limit=999")
        # FastAPI should reject limit > 200 with 422
        assert resp.status_code == 422

    def test_list_negative_offset_rejected(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.get("/api/memories?offset=-1")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

class TestGroups:
    def test_groups_requires_connection(self, client):
        resp = client.get("/api/memories/groups")
        assert resp.status_code == 400

    def test_groups_requires_collection(self, client, mock_cluster):
        with patch("db.Cluster", return_value=mock_cluster):
            client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "Administrator",
                "password": "password",
            })
        resp = client.get("/api/memories/groups")
        assert resp.status_code == 400

    def test_groups_returns_types_and_users(self, connected_client, mock_cluster):
        # Override query to return group data
        def _q(q, *a, **kw):
            if "type" in q and "DISTINCT" in q:
                return iter(["preference", "fact"])
            if "user_id" in q and "DISTINCT" in q:
                return iter(["u1", "u2"])
            return iter([{"total": 0}])

        mock_cluster.query.side_effect = _q

        resp = connected_client.get("/api/memories/groups")
        assert resp.status_code == 200
        body = resp.json()
        assert "type" in body or "user_id" in body

    def test_groups_sdk_error_returns_empty(self, connected_client, mock_cluster):
        # get_groups catches per-query errors internally and returns partial results;
        # a total failure still returns 200 with an empty dict rather than 500.
        mock_cluster.query.side_effect = RuntimeError("groups query failed")
        resp = connected_client.get("/api/memories/groups")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)


# ---------------------------------------------------------------------------
# Delete single document
# ---------------------------------------------------------------------------

class TestDeleteMemory:
    def test_delete_requires_connection(self, client):
        resp = client.delete("/api/memories/some-doc-id")
        assert resp.status_code == 400

    def test_delete_requires_collection(self, client, mock_cluster):
        with patch("db.Cluster", return_value=mock_cluster):
            client.post("/api/connect", json={
                "connection_string": "couchbase://localhost",
                "username": "Administrator",
                "password": "password",
            })
        resp = client.delete("/api/memories/some-doc-id")
        assert resp.status_code == 400

    def test_delete_success(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        resp = client.delete("/api/memories/mem-abc")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["doc_id"] == "mem-abc"

    def test_delete_calls_sdk_remove(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        client.delete("/api/memories/mem-abc")
        kv = cluster.bucket.return_value.scope.return_value.collection.return_value
        kv.remove.assert_called_once_with("mem-abc")

    def test_delete_not_found_returns_404(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        kv = cluster.bucket.return_value.scope.return_value.collection.return_value
        kv.remove.side_effect = DocumentNotFoundException("not found")
        resp = client.delete("/api/memories/nonexistent-doc")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_delete_sdk_error_returns_500(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        kv = cluster.bucket.return_value.scope.return_value.collection.return_value
        kv.remove.side_effect = RuntimeError("unexpected error")
        resp = client.delete("/api/memories/mem-abc")
        assert resp.status_code == 500

    def test_delete_doc_id_with_special_chars(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        doc_id = "namespace::user-123::memory-456"
        resp = client.delete(f"/api/memories/{doc_id}")
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Bulk delete
# ---------------------------------------------------------------------------

class TestBulkDelete:
    # Starlette TestClient does not support json= on DELETE; use client.request().
    def test_bulk_delete_requires_connection(self, client):
        resp = client.request("DELETE", "/api/memories/bulk",
                              json={"doc_ids": ["a", "b"]})
        assert resp.status_code == 400

    def test_bulk_delete_success(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        resp = client.request("DELETE", "/api/memories/bulk",
                              json={"doc_ids": ["mem-abc", "mem-xyz"]})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["deleted"]) == {"mem-abc", "mem-xyz"}
        assert body["errors"] == []

    def test_bulk_delete_partial_failure(self, connected_client_with_docs):
        client, cluster = connected_client_with_docs
        kv = cluster.bucket.return_value.scope.return_value.collection.return_value

        def _remove(doc_id):
            if doc_id == "mem-bad":
                raise DocumentNotFoundException("not found")

        kv.remove.side_effect = _remove

        resp = client.request("DELETE", "/api/memories/bulk",
                              json={"doc_ids": ["mem-abc", "mem-bad"]})
        assert resp.status_code == 200
        body = resp.json()
        assert "mem-abc" in body["deleted"]
        assert len(body["errors"]) == 1
        assert body["errors"][0]["doc_id"] == "mem-bad"

    def test_bulk_delete_empty_list(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.request("DELETE", "/api/memories/bulk",
                              json={"doc_ids": []})
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] == []
        assert body["errors"] == []

    def test_bulk_delete_missing_body_returns_422(self, connected_client_with_docs):
        client, _ = connected_client_with_docs
        resp = client.request("DELETE", "/api/memories/bulk")
        assert resp.status_code == 422
