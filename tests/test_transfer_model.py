"""The database must enforce the transfer rules without any API in front of it."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Transfer
from tests.test_models import make_account


@pytest.fixture
def two_accounts(session):
    return make_account(session, "a@example.com"), make_account(session, "b@example.com")


def make_transfer(a, b, reference_id="t-1", **overrides) -> Transfer:
    data = dict(
        source_account_id=a.id,
        destination_account_id=b.id,
        amount=10,
        description="d",
        reference_id=reference_id,
    )
    data.update(overrides)
    return Transfer(**data)


def test_valid_transfer_row(session, two_accounts):
    a, b = two_accounts
    session.add(make_transfer(a, b))
    session.commit()


def test_source_and_destination_must_differ(session, two_accounts):
    a, _ = two_accounts
    session.add(make_transfer(a, a))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("amount", [0, -1])
def test_amount_must_be_positive(session, two_accounts, amount):
    a, b = two_accounts
    session.add(make_transfer(a, b, amount=amount))
    with pytest.raises(IntegrityError):
        session.commit()


def test_reference_is_unique_per_source_account(session, two_accounts):
    a, b = two_accounts
    session.add(make_transfer(a, b, "dup"))
    session.commit()
    session.add(make_transfer(a, b, "dup"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_reference_from_another_source_is_allowed(session, two_accounts):
    a, b = two_accounts
    session.add(make_transfer(a, b, "same"))
    session.add(make_transfer(b, a, "same"))
    session.commit()


def test_accounts_must_exist(session, two_accounts):
    a, _ = two_accounts
    session.add(make_transfer(a, a, destination_account_id=9999))
    with pytest.raises(IntegrityError):
        session.commit()


def test_transfers_cannot_be_updated(session, two_accounts):
    a, b = two_accounts
    transfer = make_transfer(a, b)
    session.add(transfer)
    session.commit()
    transfer.amount = 999
    session.add(transfer)
    with pytest.raises(IntegrityError, match="immutable"):
        session.commit()


def test_transfers_cannot_be_deleted(session, two_accounts):
    a, b = two_accounts
    transfer = make_transfer(a, b)
    session.add(transfer)
    session.commit()
    session.delete(transfer)
    with pytest.raises(IntegrityError, match="cannot be deleted"):
        session.commit()
