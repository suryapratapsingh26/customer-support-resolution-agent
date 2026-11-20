"""Provider-neutral OIDC authorization-code flow with nonce and PKCE validation."""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import BFFLoginAttempt, BFFSession


class OIDCError(Exception):
    pass


def _configured() -> tuple[str, str, str, str, str]:
    if settings.environment != "development" and not settings.bff_session_cookie_secure:
        raise HTTPException(status_code=503, detail="Sign-in cookie security is not configured.")
    required = (settings.oidc_issuer, settings.oidc_audience, settings.oidc_client_id,
                settings.oidc_client_secret, settings.oidc_redirect_uri)
    if not all(required) or not settings.oidc_allowed_algorithms:
        raise HTTPException(status_code=503, detail="Sign-in is not configured.")
    issuer_url = urlsplit(required[0])
    if issuer_url.scheme != "https" and not (
        settings.environment == "development" and issuer_url.scheme == "http"
        and issuer_url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(status_code=503, detail="Sign-in is not configured securely.")
    if settings.bff_session_ttl_seconds <= 0:
        raise HTTPException(status_code=503, detail="Sign-in is not configured.")
    return required  # type: ignore[return-value]


def _secure_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(parsed.netloc) and (parsed.scheme == "https" or (
        settings.environment == "development" and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ))


async def _discovery() -> dict:
    issuer, _, _, _, _ = _configured()
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("issuer", "").rstrip("/") != issuer.rstrip("/"):
            raise OIDCError("Issuer mismatch.")
        if not all(data.get(key) for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
            raise OIDCError("OIDC discovery response is incomplete.")
        if any(not _secure_endpoint(data[key]) for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
            raise OIDCError("OIDC discovery contains an insecure endpoint.")
        return data
    except Exception as exc:
        raise OIDCError("Identity provider discovery failed.") from exc


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


async def begin_login(db: Session) -> tuple[str, str]:
    _, _, client_id, _, redirect_uri = _configured()
    metadata = await _discovery()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    browser_binding = secrets.token_urlsafe(32)
    verifier = _b64(secrets.token_bytes(48))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    db.execute(delete(BFFLoginAttempt).where(BFFLoginAttempt.expires_at < datetime.now(timezone.utc)))
    db.add(BFFLoginAttempt(
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        browser_binding_hash=hashlib.sha256(browser_binding.encode()).hexdigest(), nonce=nonce,
        code_verifier=verifier, expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    ))
    db.commit()
    query = urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri,
        "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    auth_endpoint = metadata["authorization_endpoint"]
    separator = "&" if urlsplit(auth_endpoint).query else "?"
    return f"{auth_endpoint}{separator}{query}", browser_binding


async def complete_login(db: Session, code: str, state: str, browser_binding: str | None) -> tuple[BFFSession, str]:
    issuer, audience, client_id, client_secret, redirect_uri = _configured()
    now = datetime.now(timezone.utc)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    attempt = db.scalar(select(BFFLoginAttempt).where(
        BFFLoginAttempt.state_hash == state_hash
    ).with_for_update())
    if (attempt is None or attempt.expires_at.replace(tzinfo=timezone.utc) <= now
            or not browser_binding or not secrets.compare_digest(
                attempt.browser_binding_hash, hashlib.sha256(browser_binding.encode()).hexdigest()
            )):
        raise OIDCError("Login state is invalid or expired.")
    nonce, verifier = attempt.nonce, attempt.code_verifier
    db.delete(attempt)
    db.commit()
    metadata = await _discovery()
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            token_response = await client.post(metadata["token_endpoint"], data={
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": redirect_uri, "code_verifier": verifier,
            }, auth=(client_id, client_secret))
        token_response.raise_for_status()
        id_token = token_response.json()["id_token"]
        jwks_url = settings.oidc_jwks_url or metadata["jwks_uri"]
        if not _secure_endpoint(jwks_url):
            raise OIDCError("JWKS endpoint is insecure.")
        key = jwt.PyJWKClient(jwks_url, timeout=8).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token, key, algorithms=settings.oidc_allowed_algorithms,
            audience=audience, issuer=issuer,
            options={"require": ["iss", "aud", "exp", "iat", "sub"]},
            leeway=30,
        )
        if not isinstance(claims.get("sub"), str) or not claims["sub"].strip() or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OIDCError("ID token claims are invalid.")
        roles_raw = claims.get(settings.oidc_roles_claim, [])
        ids_raw = claims.get(settings.oidc_customer_ids_claim, [])
        if not isinstance(roles_raw, list) or not all(isinstance(role, str) for role in roles_raw):
            raise OIDCError("Role claims are invalid.")
        if not isinstance(ids_raw, list) or not all(type(value) is int and value > 0 for value in ids_raw):
            raise OIDCError("Customer authorization claims are invalid.")
        roles = sorted(set(roles_raw))
        if settings.oidc_reviewer_role not in roles and settings.oidc_agent_role not in roles:
            raise OIDCError("No support permissions were granted.")
        audiences = claims.get("aud")
        if (("azp" in claims and claims["azp"] != client_id)
                or (isinstance(audiences, list) and len(audiences) > 1 and claims.get("azp") != client_id)):
            raise OIDCError("ID token authorized party is invalid.")
        raw_session = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        session = BFFSession(
            token_hash=hashlib.sha256(raw_session.encode()).hexdigest(),
            subject=claims["sub"], email=claims.get("email"),
            display_name=claims.get("name") or claims.get("preferred_username"),
            roles=roles, customer_ids=sorted(set(ids_raw)), csrf_token=csrf,
            expires_at=now + timedelta(seconds=settings.bff_session_ttl_seconds),
        )
        db.add(session)
        db.commit()
        return session, raw_session
    except OIDCError:
        raise
    except Exception as exc:
        db.rollback()
        raise OIDCError("Identity verification failed.") from exc


def session_from_request(request: Request, db: Session) -> BFFSession | None:
    raw = request.cookies.get(settings.bff_session_cookie_name)
    if not raw:
        return None
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    session = db.get(BFFSession, token_hash)
    if session is None:
        return None
    if session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    return session


def cookie_options() -> dict:
    return {"key": settings.bff_session_cookie_name, "httponly": True,
            "secure": settings.bff_session_cookie_secure, "samesite": "lax",
            "path": "/", "max_age": settings.bff_session_ttl_seconds}
