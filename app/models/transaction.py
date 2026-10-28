from datetime import datetime
from enum import Enum

from sqlalchemy import DDL, CheckConstraint, Column, Index, UniqueConstraint, event
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime, utcnow


class TransactionType(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    __table_args__ = (
        # Idempotency: same reference_id is allowed across accounts, never within one.
        UniqueConstraint(
            "account_id", "reference_id", name="uq_transactions_account_reference"
        ),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("type IN ('credit', 'debit')", name="ck_transactions_type_valid"),
        CheckConstraint(
            "length(trim(reference_id)) > 0", name="ck_transactions_reference_not_blank"
        ),
        # Serves "latest first" history per account.
        Index("ix_transactions_account_created_at", "account_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id")
    # Persist the lowercase value ("credit"/"debit"), not the enum member name.
    type: TransactionType = Field(
        sa_column=Column(
            "type",
            SAEnum(
                TransactionType,
                values_callable=lambda enum: [member.value for member in enum],
                native_enum=False,
                create_constraint=False,
                length=10,
            ),
            nullable=False,
        )
    )
    amount: int
    description: str = Field(max_length=255)
    reference_id: str = Field(max_length=100)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(UTCDateTime(), nullable=False)
    )


# Immutability enforced by the database itself, not only by the absence of routes.
_NO_UPDATE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_transactions_no_update
    BEFORE UPDATE ON transactions
    BEGIN
        SELECT RAISE(ABORT, 'transactions are immutable');
    END
    """
)
_NO_DELETE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_transactions_no_delete
    BEFORE DELETE ON transactions
    BEGIN
        SELECT RAISE(ABORT, 'transactions cannot be deleted');
    END
    """
)
event.listen(
    Transaction.__table__, "after_create", _NO_UPDATE.execute_if(dialect="sqlite")
)
event.listen(
    Transaction.__table__, "after_create", _NO_DELETE.execute_if(dialect="sqlite")
)
