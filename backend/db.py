from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, QueryOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import (
    CouchbaseException,
    QueryIndexAlreadyExistsException,
    QueryIndexNotFoundException,
)
from datetime import timedelta
from typing import Optional, Dict, Any, List
import threading
import time


class ConnectionManager:
    def __init__(self):
        self._cluster: Optional[Cluster] = None
        self._bucket_name: Optional[str] = None
        self._scope_name: Optional[str] = None
        self._collection_name: Optional[str] = None
        self._connection_string: Optional[str] = None
        self._lock = threading.Lock()

    def connect(self, connection_string: str, username: str, password: str) -> List[str]:
        with self._lock:
            if self._cluster:
                try:
                    self._cluster.close()
                except Exception:
                    pass

            auth = PasswordAuthenticator(username, password)
            self._cluster = Cluster(connection_string, ClusterOptions(auth))
            self._cluster.wait_until_ready(timedelta(seconds=15))
            self._connection_string = connection_string
            self._bucket_name = None
            self._scope_name = None
            self._collection_name = None

        return self.list_buckets()

    def disconnect(self) -> None:
        with self._lock:
            if self._cluster:
                try:
                    self._cluster.close()
                except Exception:
                    pass
                self._cluster = None
            self._bucket_name = None
            self._scope_name = None
            self._collection_name = None
            self._connection_string = None

    def set_collection(self, bucket: str, scope: str, collection: str) -> None:
        self._bucket_name = bucket
        self._scope_name = scope
        self._collection_name = collection

    @property
    def is_connected(self) -> bool:
        return self._cluster is not None

    @property
    def has_collection(self) -> bool:
        return self._collection_name is not None

    @property
    def connection_info(self) -> dict:
        return {
            "connection_string": self._connection_string,
            "bucket": self._bucket_name,
            "scope": self._scope_name,
            "collection": self._collection_name,
        }

    def list_buckets(self) -> List[str]:
        buckets = self._cluster.buckets().get_all_buckets()
        # SDK 4.x returns List[BucketSettings], not a dict
        if isinstance(buckets, dict):
            return list(buckets.keys())
        return [b.name for b in buckets]

    def list_scopes(self, bucket: str) -> List[str]:
        scopes = self._cluster.bucket(bucket).collections().get_all_scopes()
        return [s.name for s in scopes]

    def list_collections(self, bucket: str, scope: str) -> List[str]:
        scopes = self._cluster.bucket(bucket).collections().get_all_scopes()
        for s in scopes:
            if s.name == scope:
                return [c.name for c in s.collections]
        return []

    def _col_path(self) -> str:
        b, s, c = self._bucket_name, self._scope_name, self._collection_name
        return f"`{b}`.`{s}`.`{c}`"

    def _build_where(
        self,
        params: Dict[str, Any],
        search: Optional[str],
        type_filter: Optional[str],
        user_filter: Optional[str],
        time_range: Optional[str],
    ) -> str:
        # Builds the WHERE clause shared by browsing, clustering-input, and any
        # other filtered read. Mutates `params` in place with the named
        # parameters each condition references. The non-search filters (user,
        # type, time) always apply and also scope the text LIKE search — but
        # they must NOT block an explicit block ID / document key lookup.
        from datetime import datetime, timedelta, timezone

        scoped_conditions: List[str] = []

        if type_filter:
            scoped_conditions.append("m.`type` = $type_filter")
            params["type_filter"] = type_filter
        if user_filter:
            scoped_conditions.append("m.user_id = $user_filter")
            params["user_filter"] = user_filter
        if time_range:
            deltas = {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}
            delta = deltas.get(time_range)
            if delta:
                time_from = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                # Compares created_at as ISO 8601 string; docs without created_at are excluded.
                scoped_conditions.append("m.created_at IS NOT MISSING AND m.created_at >= $time_from")
                params["time_from"] = time_from

        if search:
            params["search_exact"] = search
            params["search_like"] = f"%{search.lower()}%"
            # Exact match on the Couchbase document key OR the block_id field always
            # wins regardless of user/type/time filters — a block ID uniquely identifies
            # one memory and should always be findable by ID.
            exact_clause = "(META(m).id = $search_exact OR m.block_id = $search_exact)"
            if scoped_conditions:
                scoped_clause = " AND ".join(scoped_conditions)
                like_clause = f"(LOWER(TO_STRING(m)) LIKE $search_like AND {scoped_clause})"
            else:
                like_clause = "LOWER(TO_STRING(m)) LIKE $search_like"
            return f"WHERE {exact_clause} OR {like_clause}"
        if scoped_conditions:
            return f"WHERE {' AND '.join(scoped_conditions)}"
        # Always-true predicate on the document key so the planner has a
        # sargable clause to match against idx_mm_docid — a bare query with
        # no WHERE at all won't pick up any secondary index and falls back
        # to requiring a primary index.
        return "WHERE META(m).id IS NOT MISSING"

    def query_documents(
        self,
        search: Optional[str] = None,
        type_filter: Optional[str] = None,
        user_filter: Optional[str] = None,
        time_range: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        path = self._col_path()
        params: Dict[str, Any] = {"lim": limit, "off": offset}
        where = self._build_where(params, search, type_filter, user_filter, time_range)

        count_q = f"SELECT COUNT(*) AS total FROM {path} AS m {where}"
        count_rows = list(self._cluster.query(count_q, QueryOptions(named_parameters=params)))
        total = count_rows[0]["total"] if count_rows else 0

        data_q = f"""
            SELECT META(m).id AS __cb_key,
                   META(m).cas AS __cb_cas,
                   META(m).expiration AS __cb_expiry,
                   META(m).type AS __cb_doc_type,
                   m.*
            FROM {path} AS m
            {where}
            ORDER BY META(m).id
            LIMIT $lim OFFSET $off
        """
        docs = list(self._cluster.query(data_q, QueryOptions(named_parameters=params)))

        return {"documents": docs, "total": total, "offset": offset, "limit": limit}

    def query_text_for_clustering(
        self,
        search: Optional[str] = None,
        type_filter: Optional[str] = None,
        user_filter: Optional[str] = None,
        time_range: Optional[str] = None,
        max_docs: int = 500,
    ) -> Dict[str, Any]:
        # Returns a lightweight id + primary-text projection for EVERY memory
        # matching the current filter (typically a single user), not just the
        # page the dashboard is showing — this is what "Auto Group" clusters
        # over. Only the fields getPrimaryText() looks at are projected, so
        # embeddings and other bulky fields never leave Couchbase. Capped at
        # max_docs (ordered most-recent-first) so a user with a very large
        # memory set stays within what one LLM call can reliably cluster; the
        # `truncated` flag lets the UI say so rather than silently drop memories.
        path = self._col_path()
        params: Dict[str, Any] = {"lim": max_docs}
        where = self._build_where(params, search, type_filter, user_filter, time_range)

        count_q = f"SELECT COUNT(*) AS total FROM {path} AS m {where}"
        count_rows = list(self._cluster.query(count_q, QueryOptions(named_parameters=params)))
        total = count_rows[0]["total"] if count_rows else 0

        data_q = f"""
            SELECT META(m).id AS id,
                   m.summary, m.content, m.fact, m.text, m.message
            FROM {path} AS m
            {where}
            ORDER BY m.created_at DESC
            LIMIT $lim
        """
        docs = list(self._cluster.query(data_q, QueryOptions(named_parameters=params)))
        return {"documents": docs, "total": total, "truncated": total > len(docs), "max": max_docs}

    def query_documents_by_ids(self, ids: List[str]) -> Dict[str, Any]:
        # Fetches full documents for an explicit set of keys — used to page
        # through a saved/AI group whose membership spans more memories than
        # one browse page. Callers pass one page's worth of ids at a time, so
        # the IN list stays small and idx_mm_docid (META().id) satisfies it.
        if not ids:
            return {"documents": []}
        path = self._col_path()
        params = {"ids": ids}
        data_q = f"""
            SELECT META(m).id AS __cb_key,
                   META(m).cas AS __cb_cas,
                   META(m).expiration AS __cb_expiry,
                   META(m).type AS __cb_doc_type,
                   m.*
            FROM {path} AS m
            WHERE META(m).id IN $ids
            ORDER BY META(m).id
        """
        docs = list(self._cluster.query(data_q, QueryOptions(named_parameters=params)))
        return {"documents": docs}

    def get_groups(self) -> Dict[str, Any]:
        path = self._col_path()
        groups: Dict[str, Any] = {}

        try:
            type_q = f"SELECT DISTINCT RAW m.`type` FROM {path} AS m WHERE m.`type` IS NOT MISSING AND m.`type` IS NOT NULL"
            types = [r for r in self._cluster.query(type_q) if r]
            if types:
                groups["type"] = types
        except Exception:
            pass

        try:
            user_q = f"SELECT DISTINCT RAW m.user_id FROM {path} AS m WHERE m.user_id IS NOT MISSING AND m.user_id IS NOT NULL"
            users = [r for r in self._cluster.query(user_q) if r]
            if users:
                groups["user_id"] = users
        except Exception:
            pass

        return groups

    def update_document(self, doc_id: str, data: Dict[str, Any]) -> None:
        col = (
            self._cluster
            .bucket(self._bucket_name)
            .scope(self._scope_name)
            .collection(self._collection_name)
        )
        col.upsert(doc_id, data)

    def delete_document(self, doc_id: str) -> None:
        col = (
            self._cluster
            .bucket(self._bucket_name)
            .scope(self._scope_name)
            .collection(self._collection_name)
        )
        col.remove(doc_id)

    # Secondary indexes covering the predicates query_documents() actually
    # filters on. These are always tried first — a primary index scans every
    # document for every query and isn't recommended in production, so it's
    # only created as a fallback (see create_primary_index below) when these
    # targeted indexes can't be created or don't resolve retrieval.
    #
    # idx_mm_docid indexes only the document key (not the document body) so
    # the unfiltered "browse everything" view and its ORDER BY META(m).id
    # pagination can be satisfied by an index scan instead of falling back
    # to a primary index.
    _RECOMMENDED_INDEXES = {
        "idx_mm_docid": "META().id",
        "idx_mm_type": "`type`",
        "idx_mm_user_id": "user_id",
        "idx_mm_created_at": "created_at",
        "idx_mm_block_id": "block_id",
    }

    # Last-resort fallback name, used only by create_primary_index() below.
    _PRIMARY_INDEX_NAME = "idx_mm_primary"

    _DDL_RETRY_ATTEMPTS = 3
    _DDL_RETRY_WAIT_SECONDS = 2

    def _execute_ddl(self, statement: str) -> None:
        # cluster.query() is lazy — the SDK doesn't submit anything to the
        # server until the result is iterated (or .execute() is called), so
        # the statement must actually be consumed here or it silently never
        # runs. Capella's DDL path is also flakier than self-managed
        # Server's, so a transient CouchbaseException gets a few retries
        # rather than forcing the caller to redo the whole index flow.
        last_err = None
        for attempt in range(self._DDL_RETRY_ATTEMPTS):
            try:
                list(self._cluster.query(statement))
                return
            except QueryIndexAlreadyExistsException:
                return
            except CouchbaseException as e:
                last_err = e
                if attempt < self._DDL_RETRY_ATTEMPTS - 1:
                    time.sleep(self._DDL_RETRY_WAIT_SECONDS)
        raise last_err

    def _wait_for_indexes_online(self, names: List[str], timeout_seconds: float) -> None:
        # CREATE INDEX returns as soon as the index is registered, not once it's
        # built and online. On Capella this gap is worse than on self-managed
        # Server: the query and indexer services run on separate nodes, so a
        # freshly created index can be briefly invisible even to a
        # collection-scoped lookup for its own name — the SDK's own
        # watch_indexes()/build_deferred_indexes() raise
        # QueryIndexNotFoundException in that window instead of tolerating
        # "not visible yet", so we poll get_all_indexes() ourselves and treat
        # a missing name the same as "not online yet". Only that specific
        # exception is tolerated — anything else (e.g. a Capella credential
        # that can CREATE INDEX but lacks privileges to list indexes) is a
        # real failure and must not be swallowed into a misleading timeout.
        index_mgr = (
            self._cluster
            .bucket(self._bucket_name)
            .scope(self._scope_name)
            .collection(self._collection_name)
            .query_indexes()
        )
        deadline = time.monotonic() + timeout_seconds
        pending = set(names)
        while pending:
            try:
                states = {idx.name: idx.state for idx in index_mgr.get_all_indexes()}
            except QueryIndexNotFoundException:
                states = {}
            pending = {n for n in pending if states.get(n) != "online"}
            if not pending:
                break
            if any(states.get(n) == "deferred" for n in pending):
                index_mgr.build_deferred_indexes()
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Indexes did not come online in time: {', '.join(sorted(pending))}"
                )
            time.sleep(1)

    def create_recommended_indexes(self, timeout_seconds: float = 60) -> List[str]:
        path = self._col_path()
        names = list(self._RECOMMENDED_INDEXES.keys())
        for name, key in self._RECOMMENDED_INDEXES.items():
            self._execute_ddl(f"CREATE INDEX `{name}` IF NOT EXISTS ON {path} ({key})")
        self._wait_for_indexes_online(names, timeout_seconds)
        return names

    def create_primary_index(self, timeout_seconds: float = 60) -> str:
        # Only reached as a last resort when the targeted secondary indexes
        # above can't satisfy a query on Capella (e.g. still building, or the
        # credential can't manage GSIs the way this needs). A primary index
        # scans every document body for every query, so it's deliberately
        # not created by default — see the _RECOMMENDED_INDEXES comment —
        # but it guarantees memories stay retrievable when the targeted
        # indexes fall short.
        path = self._col_path()
        name = self._PRIMARY_INDEX_NAME
        self._execute_ddl(f"CREATE PRIMARY INDEX `{name}` IF NOT EXISTS ON {path}")
        self._wait_for_indexes_online([name], timeout_seconds)
        return name
