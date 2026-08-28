"""Request-origin protections for the local HERMES API.

A localhost API can still be reached by a malicious webpage running in the
user's browser (DNS-rebinding aside, the browser will happily POST to
127.0.0.1). These helpers enforce:

* loopback-only client addresses;
* a hard refusal to serve sensitive endpoints when the server was started
  externally exposed (``--allow-external``);
* a custom request header requirement so simple cross-site form posts and
  ``no-cors`` fetches cannot reach the sensitive endpoints.
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import HTTPException, Request

# Client hosts accepted as "local". ``testclient`` is the synthetic host used
# by FastAPI's in-process TestClient.
_LOOPBACK_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

# Custom header every legitimate HERMES UI request must carry. A cross-origin
# fetch from a malicious page cannot set arbitrary headers without passing a
# CORS preflight, which the locked-down CORS policy denies.
CLIENT_HEADER = "X-Hermes-Client"
CLIENT_HEADER_VALUE = "hermes-ui"
SESSION_HEADER = "X-Hermes-Session"

_state_lock = threading.Lock()
_externally_exposed = False


def set_external_exposure(enabled: bool) -> None:
    """Records whether the server is bound to a non-loopback address."""
    global _externally_exposed
    with _state_lock:
        _externally_exposed = bool(enabled)


def is_externally_exposed() -> bool:
    with _state_lock:
        return _externally_exposed


def require_loopback(request: Request) -> None:
    """Rejects the request unless it arrives from the local machine."""
    if is_externally_exposed():
        raise HTTPException(
            status_code=403,
            detail="This endpoint is disabled while HERMES is externally exposed.",
        )
    client = request.client
    host: Optional[str] = client.host if client else None
    if host not in _LOOPBACK_CLIENT_HOSTS:
        raise HTTPException(status_code=403, detail="Loopback connections only.")


def require_client_header(request: Request) -> None:
    """Rejects requests missing the custom HERMES client header."""
    value = request.headers.get(CLIENT_HEADER, "")
    if value != CLIENT_HEADER_VALUE:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required header {CLIENT_HEADER}.",
        )


def session_token_from_request(request: Request) -> Optional[str]:
    return request.headers.get(SESSION_HEADER) or None


def validate_session_or_401(request: Request) -> str:
    """Requires a valid local session token on the request."""
    from app.services.folder_access import get_token_stores

    token = session_token_from_request(request)
    if not get_token_stores().validate_session_token(token):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid local session token.",
        )
    return token
