import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


def _roles_are_separate() -> bool:
    request_key = settings.approval_request_api_key
    review_key = settings.approval_api_key
    request_actor = settings.approval_request_actor_id
    review_actor = settings.approval_actor_id
    return bool(
        request_key and len(request_key.strip()) >= 32
        and review_key and len(review_key.strip()) >= 32
        and request_actor and request_actor.strip() and review_actor and review_actor.strip()
        and not secrets.compare_digest(request_key, review_key)
        and request_actor.strip() != review_actor.strip()
    )


def require_approval_actor(x_approval_token: str | None = Header(default=None)) -> str:
    """Authenticate the configured approval operator without trusting client identity."""
    expected = settings.approval_api_key
    actor_id = settings.approval_actor_id
    if not expected or not actor_id or not _roles_are_separate():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refund approval operations are not configured.",
        )
    if not x_approval_token or not secrets.compare_digest(x_approval_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Approval operator authentication required.",
        )
    return actor_id.strip()


def require_approval_requester(x_approval_request_token: str | None = Header(default=None)) -> str:
    """Authenticate the service identity allowed to submit requests, not review them."""
    expected = settings.approval_request_api_key
    actor_id = settings.approval_request_actor_id
    if not expected or not actor_id or not _roles_are_separate():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refund approval request operations are not configured.",
        )
    if not x_approval_request_token or not secrets.compare_digest(x_approval_request_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Approval request service authentication required.",
        )
    return actor_id.strip()
