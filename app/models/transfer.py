from datetime import datetime

from sqlalchemy import DDL, CheckConstraint, Column, UniqueConstraint, event
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime, utcnow

# A transfer writes two ordinary ledger rows with references
# "transfer:<id>:debit" and "transfer:<id>:credit". Clients may not use this
# prefix themselves, so they can never collide with (or pre-empt) a transfer.
LEG_REFERENCE_PREFIX = "transfer:"


class Transfer(SQLModel, table=True):
    """Record of a money transfer. The money itself moves as a debit on the source
    account and a credit on the destination account, both in the ledger. The balance
    changes, the transfer row and both ledger rows commit together or not at all."""

    __tablename__ = "transfers"
    __table_args__ = (
        # Idempotency for transfers: one reference_id per sending account.
        UniqueConstraint(
            "source_account_id", "reference_id", name="uq_transfers_source_reference"
        ),
        CheckConstraint("amount > 0", name="ck_transfers_amount_positive"),
        CheckConstraint(
            "source_account_id <> destination_account_id",
            name="ck_transfers_distinct_accounts",
        ),
        CheckConstraint(
            "length(trim(reference_id)) > 0", name="ck_transfers_reference_not_blank"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source_account_id: int = Field(foreign_key="accounts.id", index=True)
    destination_account_id: int = Field(foreign_key="accounts.id", index=True)
    amount: int
    description: str = Field(max_length=255)
    reference_id: str = Field(max_length=100)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(UTCDateTime(), nullable=False)
    )


# Like transactions, transfers are immutable at the database level.
_NO_UPDATE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_transfers_no_update
    BEFORE UPDATE ON transfers
    BEGIN
        SELECT RAISE(ABORT, 'transfers are immutable');
    END
    """
)
_NO_DELETE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_transfers_no_delete
    BEFORE DELETE ON transfers
    BEGIN
        SELECT RAISE(ABORT, 'transfers cannot be deleted');
    END
    """
)
event.listen(Transfer.__table__, "after_create", _NO_UPDATE.execute_if(dialect="sqlite"))
event.listen(Transfer.__table__, "after_create", _NO_DELETE.execute_if(dialect="sqlite"))
