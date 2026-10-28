import math
from dataclasses import dataclass

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.exceptions import AccountNotFoundError, InsufficientBalanceError
from app.models import Account, Transaction, TransactionType


@dataclass
class TransactionOutcome:
    transaction: Transaction
    already_exists: bool
    account_balance: int


def _find_by_reference(
    session: Session, account_id: int, reference_id: str
) -> Transaction | None:
    return session.exec(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.reference_id == reference_id,
        )
    ).first()


def apply_balance_change(
    session: Session, account_id: int, tx_type: TransactionType, amount: int
) -> None:
    """Change the balance with ONE SQL statement, so there is no read-then-write gap.

    A debit carries its own `balance >= amount` guard in the WHERE clause. If two
    debits race, the database serializes them and the second one matches 0 rows
    instead of overdrawing the account.
    """
    if tx_type == TransactionType.CREDIT:
        statement = (
            update(Account)
            .where(Account.id == account_id)
            .values(balance=Account.balance + amount)
        )
    else:
        statement = (
            update(Account)
            .where(Account.id == account_id, Account.balance >= amount)
            .values(balance=Account.balance - amount)
        )

    result = session.exec(statement.execution_options(synchronize_session=False))
    if result.rowcount != 1:
        if tx_type == TransactionType.DEBIT:
            raise InsufficientBalanceError()
        raise AccountNotFoundError()


def _outcome(
    session: Session, transaction: Transaction, already_exists: bool
) -> TransactionOutcome:
    balance = session.exec(
        select(Account.balance).where(Account.id == transaction.account_id)
    ).one()
    return TransactionOutcome(transaction, already_exists, balance)


def create_transaction(
    session: Session,
    account_id: int,
    tx_type: TransactionType,
    amount: int,
    description: str,
    reference_id: str,
) -> TransactionOutcome:
    # Fast path: a repeated reference_id is answered before anything is touched. This
    # also means a retried debit is reported as "already exists", not as insufficient.
    existing = _find_by_reference(session, account_id, reference_id)
    if existing is not None:
        return _outcome(session, existing, already_exists=True)

    # Balance update + ledger row share ONE database transaction: one commit, or
    # a rollback that undoes both.
    try:
        apply_balance_change(session, account_id, tx_type, amount)
        transaction = Transaction(
            account_id=account_id,
            type=tx_type,
            amount=amount,
            description=description,
            reference_id=reference_id,
        )
        session.add(transaction)
        session.commit()
    except IntegrityError:
        session.rollback()  # also undoes the balance change above
        # Two identical requests raced past the fast path; the unique constraint
        # let exactly one win. The loser is a duplicate, not an error.
        existing = _find_by_reference(session, account_id, reference_id)
        if existing is None:
            raise
        return _outcome(session, existing, already_exists=True)
    except Exception:
        session.rollback()
        raise

    session.refresh(transaction)
    return _outcome(session, transaction, already_exists=False)


def list_transactions(
    session: Session,
    account_id: int,
    tx_type: TransactionType | None,
    page: int,
    limit: int,
) -> tuple[list[Transaction], int, int]:
    """Returns (items, total_records, total_pages), newest first."""
    conditions = [Transaction.account_id == account_id]
    if tx_type is not None:
        conditions.append(Transaction.type == tx_type)

    total_records = session.exec(
        select(func.count()).select_from(Transaction).where(*conditions)
    ).one()

    items = session.exec(
        select(Transaction)
        .where(*conditions)
        # id breaks ties between rows created in the same instant
        .order_by(col(Transaction.created_at).desc(), col(Transaction.id).desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    total_pages = math.ceil(total_records / limit)
    return list(items), total_records, total_pages
