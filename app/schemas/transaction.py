from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import TransactionType
from app.models.transfer import LEG_REFERENCE_PREFIX

# Whole numbers only (the spec uses 50, 150, ...). strict=True means 50.5, "50"
# and true are rejected instead of being coerced. The cap keeps balance sums far
# below SQLite's 64-bit integer limit.
MAX_AMOUNT = 1_000_000_000_000

Amount = Annotated[int, Field(strict=True, gt=0, le=MAX_AMOUNT)]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
ReferenceId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TransactionType
    amount: Amount
    description: Description
    reference_id: ReferenceId

    @field_validator("reference_id")
    @classmethod
    def _not_in_reserved_namespace(cls, value: str) -> str:
        # Transfers write their own ledger rows under this prefix.
        if value.lower().startswith(LEG_REFERENCE_PREFIX):
            raise ValueError(f"reference_id must not start with '{LEG_REFERENCE_PREFIX}'")
        return value


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    type: TransactionType
    amount: int
    description: str
    reference_id: str
    created_at: datetime


class TransactionResult(BaseModel):
    """Response to POST. `already_exists` is true when reference_id was seen before
    for this account: nothing was created and the balance did not change."""

    transaction: TransactionRead
    already_exists: bool
    account_balance: int


class Pagination(BaseModel):
    page: int
    limit: int
    total_records: int
    total_pages: int


class TransactionPage(BaseModel):
    items: list[TransactionRead]
    pagination: Pagination
