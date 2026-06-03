"""Stage 5: self-signed JWT auth.

Locks /chat behind a bearer token signed with the local JWT_SECRET using HS256.
No external identity provider. verify() always passes algorithms=["HS256"]
explicitly, which is what closes the 'alg: none' forgery and the HS/RS
algorithm-confusion attacks. Mint a token for testing with:

    uv run python -m agentic_vault.auth mint [subject]
"""

import datetime as dt
import hmac
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentic_vault.config import settings

_ALGORITHM = "HS256"
_DEFAULT_TTL = dt.timedelta(hours=12)


def issue(subject: str, ttl: dt.timedelta = _DEFAULT_TTL) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": subject, "iat": now, "exp": now + ttl}
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM
    )


def verify(token: str) -> dict[str, Any]:
    return jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=[_ALGORITHM]
    )


def check_password(provided: str) -> bool:
    """Constant-time comparison against the configured login password."""
    return hmac.compare_digest(provided, settings.app_password.get_secret_value())


_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """FastAPI dependency: 401 unless the request carries a valid bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify(credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return str(claims["sub"])


def _main() -> None:
    import sys

    args = sys.argv[1:]
    if not args or args[0] != "mint":
        print("usage: python -m agentic_vault.auth mint [subject]")
        raise SystemExit(2)
    subject = args[1] if len(args) > 1 else "dev"
    print(issue(subject))


if __name__ == "__main__":
    _main()
