"""End-to-end auth tests through the FastAPI TestClient.

Covers: signup, login, wrong password, duplicate email, password length,
session cookie attributes, /me, logout cookie clearing, password hashing.
"""

import bcrypt

from src.auth import hash_password, verify_password
from src.models import User


SIGNUP_PAYLOAD = {
    "email": "alex@example.com",
    "password": "hunter2hunter2",
    "display_name": "Alex",
}


# ---------- signup ----------
def test_signup_creates_user_and_sets_cookie(client, db):
    r = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alex@example.com"
    assert body["display_name"] == "Alex"
    assert "id" in body
    # Session cookie present on the client
    assert "session" in client.cookies
    # User row exists and password is hashed (not stored plaintext)
    user = db.query(User).filter(User.email == "alex@example.com").one()
    assert user.password_hash != SIGNUP_PAYLOAD["password"]
    assert user.password_hash.startswith("$2")  # bcrypt prefix


def test_signup_lowercases_email(client, db):
    payload = {**SIGNUP_PAYLOAD, "email": "Alex@EXAMPLE.com"}
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 201
    assert r.json()["email"] == "alex@example.com"
    assert db.query(User).filter(User.email == "alex@example.com").count() == 1


def test_signup_defaults_display_name_to_email_prefix(client):
    payload = {"email": "noname@example.com", "password": "hunter2hunter2"}
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 201
    assert r.json()["display_name"] == "noname"


def test_signup_rejects_short_password(client):
    payload = {**SIGNUP_PAYLOAD, "password": "short"}
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 400
    assert "at least 8" in r.json()["detail"]


def test_signup_rejects_duplicate_email(client):
    r1 = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert r1.status_code == 201
    # Clear the cookie so the second request starts "anonymous" like a real
    # returning user would.
    client.cookies.clear()
    r2 = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"].lower()


def test_signup_rejects_malformed_email(client):
    payload = {**SIGNUP_PAYLOAD, "email": "not-an-email"}
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 422  # pydantic EmailStr validation


# ---------- login ----------
def test_login_with_correct_credentials(client):
    client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = client.post("/auth/login", json={
        "email": SIGNUP_PAYLOAD["email"],
        "password": SIGNUP_PAYLOAD["password"],
    })
    assert r.status_code == 200
    assert r.json()["email"] == SIGNUP_PAYLOAD["email"]
    assert "session" in client.cookies


def test_login_with_wrong_password(client):
    client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = client.post("/auth/login", json={
        "email": SIGNUP_PAYLOAD["email"],
        "password": "wrongpassword",
    })
    assert r.status_code == 401
    assert "incorrect" in r.json()["detail"].lower()
    # Must not leak whether the email or password was wrong
    assert "email" not in r.json()["detail"].lower() or "password" in r.json()["detail"].lower()


def test_login_with_unknown_email_returns_401_not_404(client):
    """Returning 404 on unknown email would leak account existence."""
    r = client.post("/auth/login", json={
        "email": "ghost@example.com",
        "password": "hunter2hunter2",
    })
    assert r.status_code == 401


def test_login_email_is_case_insensitive(client):
    client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = client.post("/auth/login", json={
        "email": "ALEX@EXAMPLE.COM",
        "password": SIGNUP_PAYLOAD["password"],
    })
    assert r.status_code == 200


# ---------- /me and cookie ----------
def test_me_requires_auth(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_returns_current_user(authed_client):
    r = authed_client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == SIGNUP_PAYLOAD["email"]


def test_session_cookie_is_httponly_and_lax(client):
    r = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert r.status_code == 201
    set_cookie = r.headers["set-cookie"].lower()
    # httponly keeps JS from stealing the session
    assert "httponly" in set_cookie
    # samesite=lax is the right default for our same-origin frontend
    assert "samesite=lax" in set_cookie
    # In dev (ENV != prod), secure flag is off so localhost HTTP works
    assert "secure" not in set_cookie


def test_me_with_tampered_cookie_returns_401(client):
    """A cookie with a valid shape but wrong signature must not grant access."""
    client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.set("session", "not.a.valid.jwt")
    r = client.get("/auth/me")
    assert r.status_code == 401


# ---------- logout ----------
def test_logout_clears_cookie(authed_client):
    r = authed_client.post("/auth/logout")
    assert r.status_code == 200
    # After logout, /me should be unauthorized again
    r2 = authed_client.get("/auth/me")
    assert r2.status_code == 401


# ---------- password hashing unit tests ----------
def test_hash_password_uses_bcrypt():
    hashed = hash_password("hunter2hunter2")
    assert hashed.startswith("$2")
    assert bcrypt.checkpw(b"hunter2hunter2", hashed.encode())


def test_verify_password_roundtrip():
    hashed = hash_password("mysecret123")
    assert verify_password("mysecret123", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_handles_malformed_hash():
    """verify_password must never raise — return False even on garbage input."""
    assert verify_password("whatever", "not-a-valid-bcrypt-hash") is False


def test_password_over_72_bytes_is_truncated_not_rejected():
    """bcrypt ignores bytes past 72. We truncate explicitly so long passwords
    still hash deterministically instead of raising."""
    long_pw = "a" * 200
    hashed = hash_password(long_pw)
    # Same 72-byte prefix should verify the same way
    assert verify_password("a" * 72, hashed) is True
    assert verify_password("a" * 200, hashed) is True
