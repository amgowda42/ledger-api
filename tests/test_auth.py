from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from tests.conftest import CREDENTIALS

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def register_and_login(client):
    assert client.post(REGISTER, json=CREDENTIALS).status_code == 201
    response = client.post(LOGIN, json=CREDENTIALS)
    assert response.status_code == 200
    return response


def forge_token(sub="1", secret=None, expires_in=timedelta(minutes=5), algorithm="HS256"):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": sub, "iat": now, "exp": now + expires_in},
        secret or settings.jwt_secret_key,
        algorithm=algorithm,
    )


# --- register ---------------------------------------------------------------


def test_register_returns_user_without_password(client):
    response = client.post(REGISTER, json=CREDENTIALS)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in body and "hashed_password" not in body


def test_register_duplicate_email_is_case_insensitive(client):
    client.post(REGISTER, json=CREDENTIALS)
    response = client.post(
        REGISTER, json={"email": "ALICE@Example.com", "password": "another-password"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


def test_register_validation_errors_use_envelope_and_do_not_echo_password(client):
    response = client.post(REGISTER, json={"email": "not-an-email", "password": "zq7x"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {d["field"] for d in error["details"]} == {"email", "password"}
    assert "zq7x" not in response.text


def test_register_rejects_unknown_fields(client):
    response = client.post(REGISTER, json={**CREDENTIALS, "is_admin": True})
    assert response.status_code == 422


# --- login ------------------------------------------------------------------


def test_login_sets_httponly_cookie(client):
    response = register_and_login(client)
    cookie_header = response.headers["set-cookie"]
    assert cookie_header.startswith(f"{settings.cookie_name}=")
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert "Max-Age=" in cookie_header
    # the token is in the cookie only, never in the JSON body
    assert "token" not in response.text


def test_login_wrong_password_and_unknown_email_look_identical(client):
    client.post(REGISTER, json=CREDENTIALS)
    wrong_pw = client.post(LOGIN, json={**CREDENTIALS, "password": "wrong-password"})
    unknown = client.post(LOGIN, json={"email": "nobody@example.com", "password": "x"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()
    assert "set-cookie" not in wrong_pw.headers


# --- me / cookie verification ------------------------------------------------


def test_me_with_valid_cookie(client):
    register_and_login(client)
    response = client.get(ME)
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_me_without_cookie_is_401(client):
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_rejects_garbage_token(client):
    client.cookies.set(settings.cookie_name, "not.a.jwt")
    assert client.get(ME).status_code == 401


def test_me_rejects_token_signed_with_other_secret(client):
    register_and_login(client)
    client.cookies.set(
        settings.cookie_name, forge_token(secret="some-other-secret-that-is-long-enough!!")
    )
    assert client.get(ME).status_code == 401


def test_me_rejects_expired_token(client):
    register_and_login(client)
    client.cookies.set(settings.cookie_name, forge_token(expires_in=timedelta(minutes=-1)))
    assert client.get(ME).status_code == 401


def test_me_rejects_unsigned_alg_none_token(client):
    register_and_login(client)
    unsigned = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )
    client.cookies.set(settings.cookie_name, unsigned)
    assert client.get(ME).status_code == 401


def test_me_rejects_valid_token_for_nonexistent_user(client):
    client.cookies.set(settings.cookie_name, forge_token(sub="424242"))
    assert client.get(ME).status_code == 401


def test_me_rejects_token_without_expiry(client):
    token = jwt.encode({"sub": "1"}, settings.jwt_secret_key, algorithm="HS256")
    client.cookies.set(settings.cookie_name, token)
    assert client.get(ME).status_code == 401


# --- logout ------------------------------------------------------------------


def test_logout_clears_cookie(client):
    register_and_login(client)
    response = client.post(LOGOUT)
    assert response.status_code == 204
    assert client.get(ME).status_code == 401


def test_logout_without_session_is_fine(client):
    assert client.post(LOGOUT).status_code == 204


# --- envelope on non-domain errors --------------------------------------------


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
