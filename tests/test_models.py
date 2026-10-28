"""The database must enforce the integrity rules on its own, with no API in front."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import Account, Transaction, TransactionType, User


def make_user(session: Session, email: str) -> User:
    user = User(email=email, hashed_password="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def make_account(session: Session, email: str = "a@example.com") -> Account:
    user = make_user(session, email)
    account = Account(owner_id=user.id, name="Alice")
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def make_tx(account_id: int, reference_id: str = "ref-1", **overrides) -> Transaction:
    data = dict(
        account_id=account_id,
        type=TransactionType.CREDIT,
        amount=100,
        description="test",
        reference_id=reference_id,
    )
    data.update(overrides)
    return Transaction(**data)


def test_new_account_starts_at_zero_with_utc_timestamp(session):
    account = make_account(session)
    assert account.balance == 0
    assert account.created_at.tzinfo is not None


def test_negative_balance_is_rejected(session):
    account = make_account(session)
    account.balance = -1
    session.add(account)
    with pytest.raises(IntegrityError):
        session.commit()


def test_blank_account_name_is_rejected(session):
    user = make_user(session, "b@example.com")
    session.add(Account(owner_id=user.id, name="   "))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_account_per_user(session):
    account = make_account(session)
    session.add(Account(owner_id=account.owner_id, name="Second"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_duplicate_reference_in_same_account_is_rejected(session):
    account = make_account(session)
    session.add(make_tx(account.id, "dup"))
    session.commit()
    session.add(make_tx(account.id, "dup"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_reference_in_different_accounts_is_allowed(session):
    a = make_account(session, "a@example.com")
    b = make_account(session, "b@example.com")
    session.add(make_tx(a.id, "shared"))
    session.add(make_tx(b.id, "shared"))
    session.commit()


@pytest.mark.parametrize("amount", [0, -5])
def test_non_positive_amount_is_rejected(session, amount):
    account = make_account(session)
    session.add(make_tx(account.id, amount=amount))
    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_type_is_rejected_by_the_database(session):
    account = make_account(session)
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO transactions (account_id, type, amount, description, "
                "reference_id, created_at) VALUES (:a, 'refund', 10, 'x', 'r', "
                "'2026-01-01 00:00:00')"
            ),
            {"a": account.id},
        )


def test_type_is_stored_as_lowercase_value(session):
    account = make_account(session)
    session.add(make_tx(account.id, type=TransactionType.DEBIT))
    session.commit()
    stored = session.execute(text("SELECT type FROM transactions")).scalar_one()
    assert stored == "debit"


def test_blank_reference_is_rejected(session):
    account = make_account(session)
    session.add(make_tx(account.id, reference_id="  "))
    with pytest.raises(IntegrityError):
        session.commit()


def test_transaction_requires_existing_account(session):
    session.add(make_tx(account_id=9999))
    with pytest.raises(IntegrityError):
        session.commit()


def test_transactions_cannot_be_updated(session):
    account = make_account(session)
    tx = make_tx(account.id)
    session.add(tx)
    session.commit()
    tx.amount = 999
    session.add(tx)
    with pytest.raises(IntegrityError, match="immutable"):
        session.commit()


def test_transactions_cannot_be_deleted(session):
    account = make_account(session)
    tx = make_tx(account.id)
    session.add(tx)
    session.commit()
    session.delete(tx)
    with pytest.raises(IntegrityError, match="cannot be deleted"):
        session.commit()
