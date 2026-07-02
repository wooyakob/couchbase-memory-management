import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from db import ConnectionManager

SESSION_COOKIE_NAME = "mm_session_id"
SESSION_TTL_SECONDS = 1800


class SessionStore:
    """Maps opaque session ids to per-session ConnectionManager instances.

    Replaces the old module-level ConnectionManager singleton so concurrent
    browser sessions each get their own cluster/collection state instead of
    silently clobbering each other's.
    """

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._sessions: Dict[str, ConnectionManager] = {}
        self._last_used: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _evict_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            sid for sid, last in self._last_used.items()
            if now - last > self._ttl_seconds
        ]
        for sid in expired:
            manager = self._sessions.pop(sid, None)
            self._last_used.pop(sid, None)
            if manager:
                manager.disconnect()

    def get_or_create(self, session_id: Optional[str]) -> Tuple[str, ConnectionManager]:
        with self._lock:
            self._evict_expired_locked()

            if session_id and session_id in self._sessions:
                self._last_used[session_id] = time.monotonic()
                return session_id, self._sessions[session_id]

            new_id = uuid.uuid4().hex
            manager = ConnectionManager()
            self._sessions[new_id] = manager
            self._last_used[new_id] = time.monotonic()
            return new_id, manager

    def drop(self, session_id: str) -> None:
        with self._lock:
            manager = self._sessions.pop(session_id, None)
            self._last_used.pop(session_id, None)
        if manager:
            manager.disconnect()

    def all_managers(self) -> List[ConnectionManager]:
        with self._lock:
            return list(self._sessions.values())


session_store = SessionStore()
