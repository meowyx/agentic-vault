"""Unit tests for the JWT auth helpers (no HTTP, no mocks needed)."""

import datetime as dt

import jwt
import pytest

from agentic_vault import auth
from agentic_vault.config import settings


def test_issue_verify_roundtrip():
    assert auth.verify(auth.issue("alice"))["sub"] == "alice"


def test_tampered_token_is_rejected():
    token = auth.issue("alice")
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify(token + "x")


def test_expired_token_is_rejected():
    secret = settings.jwt_secret.get_secret_value()
    expired = jwt.encode(
        {"sub": "x", "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)},
        secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.verify(expired)


def test_check_password():
    assert auth.check_password(settings.app_password.get_secret_value())
    assert not auth.check_password("definitely-wrong")
