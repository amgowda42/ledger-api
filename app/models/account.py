from datetime import datetime

from sqlalchemy import CheckConstraint, Column
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime, utcnow


class Account(SQLModel, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),
        CheckConstraint("length(trim(name)) > 0", name="ck_accounts_name_not_blank"),
    )

    id: int | None = Field(default=None, primary_key=True)
    # One account per user: enforced by the unique index, not just by the API.
    owner_id: int = Field(foreign_key="users.id", unique=True, index=True)
    name: str = Field(max_length=100)
    # Whole currency units (the spec uses whole numbers: 50, 150, ...).
    balance: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(UTCDateTime(), nullable=False)
    )
