from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, QueryOptions
from couchbase.auth import PasswordAuthenticator
from datetime import timedelta
from typing import Optional, Dict, Any, List
import threading


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

    def query_documents(
        self,
        search: Optional[str] = None,
        type_filter: Optional[str] = None,
        user_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        path = self._col_path()
        conditions: List[str] = []
        params: Dict[str, Any] = {"lim": limit, "off": offset}

        if search:
            conditions.append("LOWER(TO_STRING(m)) LIKE $search")
            params["search"] = f"%{search.lower()}%"
        if type_filter:
            conditions.append("m.`type` = $type_filter")
            params["type_filter"] = type_filter
        if user_filter:
            conditions.append("m.user_id = $user_filter")
            params["user_filter"] = user_filter

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

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

    def create_primary_index(self) -> None:
        path = self._col_path()
        self._cluster.query(f"CREATE PRIMARY INDEX IF NOT EXISTS ON {path}")


connection_manager = ConnectionManager()
