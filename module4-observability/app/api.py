"""The one place the dashboard talks to the backend and Prometheus.

Every call goes through `request()`, which:
- attaches the signed-in user's access token,
- renews it once with the refresh token when the backend answers 401,
- turns backend errors into a readable `ApiError` message,
- serves sample data instead when the session is in preview mode.

Tokens live only in Streamlit's server-side session state, never in the
browser or in URLs.
"""
from __future__ import annotations

from typing import Any

import requests
import streamlit as st

import config


class ApiError(Exception):
    """A backend request failed; `str(err)` is safe to show to the user."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class SessionExpired(ApiError):
    """The login can't be renewed; the user has to sign in again."""


_FRIENDLY = {
    401: "Your session has expired. Please sign in again.",
    403: "Your account doesn't have permission to do this.",
    404: "That record no longer exists.",
    413: "The upload is too large.",
    429: "Too many requests. Please wait a moment and try again.",
}


def _error_message(response: requests.Response) -> tuple[str, str | None]:
    """Readable message + backend error code from an error response."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(detail, list):  # 422 validation errors: one line per field
        parts = []
        for item in detail:
            field = ".".join(str(p) for p in item.get("loc", [])[1:]) or "input"
            parts.append(f"{field}: {item.get('msg', 'invalid value')}")
        return "; ".join(parts) or "Some fields are invalid.", code
    if isinstance(detail, str) and detail:
        return detail, code
    if response.status_code >= 500:
        return "The backend had an internal error. Please try again.", code
    return _FRIENDLY.get(response.status_code, f"Request failed ({response.status_code})."), code


def _send(method: str, path: str, token: str | None = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return requests.request(
            method, f"{config.BACKEND_URL}{path}", headers=headers,
            timeout=config.BACKEND_TIMEOUT_SECONDS, **kwargs,
        )
    except requests.Timeout as exc:
        raise ApiError("The backend took too long to respond. Please try again.") from exc
    except requests.ConnectionError as exc:
        raise ApiError("Can't reach the backend. Check that it is running.") from exc


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> dict:
    """Returns the backend's login payload: access_token, refresh_token, user."""
    response = _send("POST", "/api/v1/auth/login", json={"email": email, "password": password})
    if response.status_code == 200:
        return response.json()
    if response.status_code == 401:
        raise ApiError("Incorrect email or password.", 401)
    if response.status_code == 429:
        retry = response.headers.get("Retry-After")
        minutes = max(1, -(-int(retry) // 60)) if retry and retry.isdigit() else None
        wait = f" for {minutes} minute(s)" if minutes else ""
        raise ApiError(f"Too many failed sign-in attempts. This account is locked{wait}.", 429)
    message, code = _error_message(response)
    raise ApiError(message, response.status_code, code)


def _refresh() -> bool:
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        return False
    response = _send("POST", "/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    if response.status_code != 200:
        return False
    data = response.json()
    st.session_state.access_token = data["access_token"]
    st.session_state.refresh_token = data.get("refresh_token", refresh_token)
    return True


def logout() -> None:
    """Revokes both tokens on the backend (always succeeds from our side)."""
    if st.session_state.get("demo"):
        return
    try:
        _send(
            "POST", "/api/v1/auth/logout", token=st.session_state.get("access_token"),
            json={"refresh_token": st.session_state.get("refresh_token")},
        )
    except ApiError:
        pass


# ---------------------------------------------------------------------------
# Authenticated requests
# ---------------------------------------------------------------------------

def request(method: str, path: str, *, raw: bool = False, **kwargs) -> Any:
    """Calls the backend as the signed-in user; returns parsed JSON (or the
    raw Response when raw=True). Raises ApiError with a readable message."""
    if st.session_state.get("demo"):
        import demo
        return demo.handle(method, path, params=kwargs.get("params"), body=kwargs.get("json"), raw=raw)

    response = _send(method, path, token=st.session_state.get("access_token"), **kwargs)
    if response.status_code == 401:
        if not _refresh():
            raise SessionExpired(_FRIENDLY[401], 401)
        response = _send(method, path, token=st.session_state.get("access_token"), **kwargs)
        if response.status_code == 401:
            raise SessionExpired(_FRIENDLY[401], 401)

    if not response.ok:
        message, code = _error_message(response)
        raise ApiError(message, response.status_code, code)
    if raw:
        return response
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError("The backend returned an unreadable response.") from exc


def get(path: str, **params) -> Any:
    return request("GET", path, params={k: v for k, v in params.items() if v is not None})


def post(path: str, body: dict | None = None) -> Any:
    return request("POST", path, json=body or {})


def patch(path: str, body: dict) -> Any:
    return request("PATCH", path, json=body)


def delete(path: str) -> Any:
    return request("DELETE", path)


def get_all(path: str, **params) -> list[dict]:
    """Follows the backend's {items,total,limit,offset} pages to the end."""
    items: list[dict] = []
    offset = 0
    while True:
        page = get(path, limit=config.PAGE_SIZE, offset=offset, **params)
        if isinstance(page, list):  # endpoint isn't paginated
            return page
        batch = page.get("items", [])
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= page.get("total", 0):
            return items


# ---------------------------------------------------------------------------
# Prometheus (no auth; aggregate numbers only)
# ---------------------------------------------------------------------------

def prometheus_value(promql: str) -> float | None:
    """Single number from an instant PromQL query, or None if unavailable."""
    if st.session_state.get("demo"):
        import demo
        return demo.prometheus_value(promql)
    try:
        response = requests.get(
            f"{config.PROMETHEUS_URL}/api/v1/query", params={"query": promql},
            timeout=config.PROMETHEUS_TIMEOUT_SECONDS,
        )
        result = response.json()["data"]["result"]
        if not result:
            return 0.0
        value = float(result[0]["value"][1])
        return None if value != value else value  # NaN (e.g. 0/0) -> None
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None
