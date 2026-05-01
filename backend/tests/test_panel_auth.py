import importlib
import queue
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    """Force config and app modules to re-read environment variables."""
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            Path(module_file).resolve().relative_to(BACKEND_DIR)
        except ValueError:
            continue
        del sys.modules[name]


def _disable_dotenv_loading(monkeypatch) -> None:
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)


def _client_with_admin_password(monkeypatch, password: str | None) -> TestClient:
    if password is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", password)

    _disable_dotenv_loading(monkeypatch)
    _clear_backend_modules()
    main = importlib.import_module("main")
    # Do not use TestClient as a context manager; that would run lifespan startup.
    return TestClient(main.app)


def test_auth_status_disabled_and_authenticated_when_admin_password_unset(monkeypatch):
    client = _client_with_admin_password(monkeypatch, None)
    try:
        response = client.get("/api/auth/status")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "authenticated": True}


def test_auth_status_disabled_and_authenticated_when_admin_password_empty(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "")
    try:
        response = client.get("/api/auth/status")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "authenticated": True}


def test_auth_status_enabled_and_unauthenticated_without_cookie(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    try:
        response = client.get("/api/auth/status")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "authenticated": False}


def test_protected_api_route_requires_auth_cookie_when_admin_password_set(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    try:
        response = client.get("/api/account/balance")
    finally:
        client.close()

    assert response.status_code == 401


def test_login_rejects_wrong_password(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    try:
        response = client.post("/api/auth/login", json={"password": "wrong-password"})
        status_response = client.get("/api/auth/status")
    finally:
        client.close()

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert status_response.status_code == 200
    assert status_response.json() == {"enabled": True, "authenticated": False}


def test_login_accepts_non_ascii_configured_password(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "密钥🔐")
    try:
        login_response = client.post(
            "/api/auth/login",
            json={"password": "密钥🔐"},
        )
        status_response = client.get("/api/auth/status")
    finally:
        client.close()

    assert login_response.status_code == 200
    assert status_response.status_code == 200
    assert status_response.json() == {"enabled": True, "authenticated": True}


def test_auth_cookie_expires_server_side(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    try:
        login_response = client.post(
            "/api/auth/login",
            json={"password": "secret-password"},
        )
        auth = importlib.import_module("api.auth")
        now = getattr(auth, "_now", lambda: 0)()
        monkeypatch.setattr(auth, "_now", lambda: now + auth.COOKIE_MAX_AGE + 1, raising=False)
        status_response = client.get("/api/auth/status")
        protected_response = client.get("/api/account/balance")
    finally:
        client.close()

    assert login_response.status_code == 200
    assert status_response.status_code == 200
    assert status_response.json() == {"enabled": True, "authenticated": False}
    assert protected_response.status_code == 401


def test_websocket_closes_after_auth_cookie_expires(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    try:
        login_response = client.post(
            "/api/auth/login",
            json={"password": "secret-password"},
        )
        auth = importlib.import_module("api.auth")
        now = auth._now()
        with client.websocket_connect("/ws") as websocket:
            monkeypatch.setattr(auth, "_now", lambda: now + auth.COOKIE_MAX_AGE + 1)
            websocket.send_text("ping")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_text()
    finally:
        client.close()

    assert login_response.status_code == 200


def test_websocket_closes_after_auth_cookie_expires_without_client_message(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    received = queue.Queue()
    try:
        auth = importlib.import_module("api.auth")
        monkeypatch.setattr(auth, "COOKIE_MAX_AGE", 1)
        login_response = client.post(
            "/api/auth/login",
            json={"password": "secret-password"},
        )
        with client.websocket_connect("/ws") as websocket:
            def receive_text():
                try:
                    received.put(websocket.receive_text())
                except Exception as exc:
                    received.put(exc)

            thread = threading.Thread(target=receive_text, daemon=True)
            thread.start()
            thread.join(3)
            closed_before_manual_close = not thread.is_alive()
            if thread.is_alive():
                websocket.close()
                thread.join(1)
    except WebSocketDisconnect as exc:
        received.put(exc)
    finally:
        client.close()

    assert login_response.status_code == 200
    assert closed_before_manual_close
    assert isinstance(received.get_nowait(), WebSocketDisconnect)


def test_login_accepts_configured_password_sets_cookie_and_authenticates(monkeypatch):
    client = _client_with_admin_password(monkeypatch, "secret-password")
    try:
        login_response = client.post(
            "/api/auth/login",
            json={"password": "secret-password"},
        )
        status_response = client.get("/api/auth/status")
    finally:
        client.close()

    assert login_response.status_code == 200
    assert "set-cookie" in login_response.headers
    assert status_response.status_code == 200
    assert status_response.json() == {"enabled": True, "authenticated": True}
