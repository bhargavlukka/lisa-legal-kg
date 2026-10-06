"""Signed bearer tokens (HS256 JWT) between the agent and the MCP servers, with role separation.

Roles map to scopes:  researcher -> lisa:read          admin -> lisa:read + lisa:admin
Every server requires lisa:read on the transport; admin-only tools additionally call `require_admin()`.
"""
from __future__ import annotations

import time
import uuid

import jwt

from lisa.common.config import AuthSettings

READ, ADMIN = "lisa:read", "lisa:admin"
ROLES = {"researcher": [READ], "admin": [READ, ADMIN]}


MIN_SECRET = 32


class AuthError(PermissionError):
    pass


def _require_strong_secret(auth: AuthSettings) -> None:
    """HS256 is only as strong as the shared secret: refuse unset, short, or copied-from-the-example secrets."""
    s = auth.secret or ""
    if not s:
        raise AuthError("LISA_AUTH_SECRET is not set")
    if len(s) < MIN_SECRET or s.upper().startswith("REPLACE") or "change-me" in s.lower():
        raise AuthError(f"LISA_AUTH_SECRET is weak or a placeholder: use >= {MIN_SECRET} random characters "
                        "(python -c \"import secrets; print(secrets.token_hex(32))\")")


def issue_token(auth: AuthSettings, subject: str, role: str, ttl_s: int | None = None) -> str:
    _require_strong_secret(auth)
    if role not in ROLES:
        raise AuthError(f"unknown role {role!r}; expected one of {sorted(ROLES)}")
    now = int(time.time())
    claims = {"iss": auth.issuer, "aud": auth.audience, "sub": subject, "role": role, "scope": " ".join(ROLES[role]),
              "iat": now, "exp": now + (ttl_s or auth.token_ttl_s), "jti": uuid.uuid4().hex}
    return jwt.encode(claims, auth.secret, algorithm="HS256")


def decode_token(auth: AuthSettings, token: str) -> dict:
    """Claims of a valid token; raises AuthError on bad signature, expiry, wrong issuer/audience or role."""
    _require_strong_secret(auth)
    try:
        claims = jwt.decode(token, auth.secret, algorithms=["HS256"], audience=auth.audience, issuer=auth.issuer,
                            options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.PyJWTError as e:
        raise AuthError(str(e)) from e
    if claims.get("role") not in ROLES or set(claims.get("scope", "").split()) != set(ROLES[claims["role"]]):
        raise AuthError("role/scope mismatch")
    return claims


class JWTVerifier:
    """mcp TokenVerifier: bearer token -> AccessToken (None rejects the request with 401)."""

    def __init__(self, auth: AuthSettings):
        self.auth = auth

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken
        try:
            c = decode_token(self.auth, token)
        except AuthError:
            return None
        return AccessToken(token=token, client_id=c["sub"], scopes=c["scope"].split(), expires_at=c["exp"],
                           subject=c["sub"], claims={"role": c["role"], "iss": c["iss"]})


def current_scopes() -> set[str] | None:
    """Scopes of the caller of the current MCP request; None when the server runs without auth (stdio/tests)."""
    from mcp.server.auth.middleware.auth_context import get_access_token
    tok = get_access_token()
    return None if tok is None else set(tok.scopes)


def require_admin(auth_enabled: bool) -> None:
    scopes = current_scopes()
    if auth_enabled and (scopes is None or ADMIN not in scopes):
        raise AuthError("admin role required")
