from dataclasses import dataclass

from fastapi import Request, Response

from db import ConnectionManager
from session_store import session_store, SESSION_COOKIE_NAME, SESSION_TTL_SECONDS


@dataclass
class SessionContext:
    session_id: str
    manager: ConnectionManager


def get_session(request: Request, response: Response) -> SessionContext:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session_id, manager = session_store.get_or_create(session_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
    )
    return SessionContext(session_id=session_id, manager=manager)
