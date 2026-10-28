from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.exceptions import AccountAlreadyExistsError, AccountNotFoundError
from app.models import Account


def create_account(session: Session, owner_id: int, name: str) -> Account:
    # balance is never taken from the client: it starts at the model default (0).
    account = Account(owner_id=owner_id, name=name)
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        # The unique index on owner_id decides, so concurrent requests are safe too.
        session.rollback()
        raise AccountAlreadyExistsError() from None
    session.refresh(account)
    return account


def get_owned_account(
    session: Session,
    account_id: int,
    owner_id: int,
    *,
    not_found_message: str | None = None,
    field: str | None = None,
) -> Account:
    """An account that doesn't exist and one that belongs to someone else look the same."""
    account = session.get(Account, account_id)
    if account is None or account.owner_id != owner_id:
        details = [{"in": "body", "field": field}] if field else None
        raise AccountNotFoundError(not_found_message, details)
    return account


def get_account_of_owner(session: Session, owner_id: int) -> Account:
    account = session.exec(select(Account).where(Account.owner_id == owner_id)).first()
    if account is None:
        raise AccountNotFoundError("You do not have an account yet")
    return account
