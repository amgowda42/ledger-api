from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.core.security import hash_password, verify_password
from app.models import User

# Verified against when the email is unknown, so "no such user" and "wrong password"
# take about the same time and can't be told apart by timing.
_DUMMY_HASH = hash_password("not-a-real-password")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(session: Session, email: str, password: str) -> User:
    user = User(email=normalize_email(email), hashed_password=hash_password(password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # The unique index is the source of truth, so concurrent registrations are safe.
        session.rollback()
        raise EmailAlreadyRegisteredError() from None
    session.refresh(user)
    return user


def authenticate_user(session: Session, email: str, password: str) -> User:
    user = session.exec(
        select(User).where(User.email == normalize_email(email))
    ).first()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentialsError()
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError()
    return user
