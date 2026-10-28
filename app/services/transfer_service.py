from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.exceptions import AccountNotFoundError, InvalidTransferError
from app.models import Account, Transaction, TransactionType, Transfer
from app.models.transfer import LEG_REFERENCE_PREFIX
from app.services import account_service
from app.services.transaction_service import apply_balance_change


@dataclass
class TransferOutcome:
    transfer: Transfer
    already_exists: bool
    source_balance: int


def _find_transfer(
    session: Session, source_account_id: int, reference_id: str
) -> Transfer | None:
    return session.exec(
        select(Transfer).where(
            Transfer.source_account_id == source_account_id,
            Transfer.reference_id == reference_id,
        )
    ).first()


def _outcome(
    session: Session, transfer: Transfer, already_exists: bool
) -> TransferOutcome:
    balance = session.exec(
        select(Account.balance).where(Account.id == transfer.source_account_id)
    ).one()
    return TransferOutcome(transfer, already_exists, balance)


def _leg_description(prefix: str, description: str) -> str:
    if description == "Transfer":  # the default: don't repeat the word
        return prefix
    return f"{prefix}: {description}"[:255]


def create_transfer(
    session: Session,
    owner_id: int,
    source_account_id: int,
    destination_account_id: int,
    amount: int,
    description: str,
    reference_id: str,
) -> TransferOutcome:
    if source_account_id == destination_account_id:
        raise InvalidTransferError()

    # You can only move money out of your own account...
    account_service.get_owned_account(
        session,
        source_account_id,
        owner_id,
        not_found_message="Source account not found",
        field="source_account_id",
    )
    # ...but you can send it to any existing account.
    if session.get(Account, destination_account_id) is None:
        raise AccountNotFoundError(
            "Destination account not found",
            [{"in": "body", "field": "destination_account_id"}],
        )

    # Fast path: a retry is answered before anything is touched, so a retried transfer
    # is reported as a duplicate even if the balance could no longer cover it.
    existing = _find_transfer(session, source_account_id, reference_id)
    if existing is not None:
        return _outcome(session, existing, already_exists=True)

    try:
        # Everything below is ONE database transaction. A failure anywhere (not enough
        # money, a constraint, a crash) leaves no trace: no balance change, no ledger
        # rows, no transfer record. A partial transfer cannot be committed.
        transfer = Transfer(
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
            amount=amount,
            description=description,
            reference_id=reference_id,
        )
        session.add(transfer)
        session.flush()  # assigns transfer.id; the unique constraint decides races here

        # Move the money, always touching the lower account id first. SQLite has a
        # single writer so it cannot deadlock, but databases with row locks could.
        movements = sorted(
            [
                (source_account_id, TransactionType.DEBIT),
                (destination_account_id, TransactionType.CREDIT),
            ]
        )
        for account_id, kind in movements:
            apply_balance_change(session, account_id, kind, amount)

        session.add(
            Transaction(
                account_id=source_account_id,
                type=TransactionType.DEBIT,
                amount=amount,
                description=_leg_description(
                    f"Transfer to account {destination_account_id}", description
                ),
                reference_id=f"{LEG_REFERENCE_PREFIX}{transfer.id}:debit",
            )
        )
        session.add(
            Transaction(
                account_id=destination_account_id,
                type=TransactionType.CREDIT,
                amount=amount,
                description=_leg_description(
                    f"Transfer from account {source_account_id}", description
                ),
                reference_id=f"{LEG_REFERENCE_PREFIX}{transfer.id}:credit",
            )
        )
        session.commit()
    except IntegrityError:
        session.rollback()  # undoes the transfer row, both balances and both legs
        # Identical requests raced past the check above; the unique constraint let
        # exactly one win. The loser is a duplicate, not an error.
        existing = _find_transfer(session, source_account_id, reference_id)
        if existing is None:
            raise
        return _outcome(session, existing, already_exists=True)
    except Exception:
        session.rollback()
        raise

    session.refresh(transfer)
    return _outcome(session, transfer, already_exists=False)
