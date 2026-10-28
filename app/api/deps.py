from typing import Annotated

from fastapi import Depends, Path
from fastapi.security import APIKeyCookie
from sqlmodel import Session

from app.core.config import settings
from app.core.exceptions import NotAuthenticatedError
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_session
from app.models import User

SessionDep = Annotated[Session, Depends(get_session)]

# Bounded so an absurd id gets a clean 422 instead of overflowing SQLite's 64-bit int.
AccountId = Annotated[
    int, Path(ge=1, le=9_223_372_036_854_775_807, description="Account id")
]

# auto_error=False so a missing cookie goes through our own error envelope.
_cookie_scheme = APIKeyCookie(name=settings.cookie_name, auto_error=False)


def get_current_user(
    session: SessionDep,
    access_token: Annotated[str | None, Depends(_cookie_scheme)],
) -> User:
    """Verify the access-token cookie on every request and load its user."""
    if not access_token:
        raise NotAuthenticatedError()
    try:
        user_id = decode_access_token(access_token)
    except InvalidTokenError:
        raise NotAuthenticatedError("Invalid or expired token") from None

    user = session.get(User, user_id)
    if user is None:  # valid signature, but the user no longer exists
        raise NotAuthenticatedError("Invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
