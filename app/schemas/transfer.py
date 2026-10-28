from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.transaction import Amount, Description, ReferenceId

AccountIdBody = Annotated[int, Field(strict=True, ge=1, le=9_223_372_036_854_775_807)]


class TransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: AccountIdBody
    destination_account_id: AccountIdBody
    amount: Amount
    reference_id: ReferenceId
    description: Description = "Transfer"


class TransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_account_id: int
    destination_account_id: int
    amount: int
    description: str
    reference_id: str
    created_at: datetime


class TransferResult(BaseModel):
    """`already_exists` is true when this reference_id was already used by the source
    account: nothing moved and the original transfer is returned. Only the source
    balance is shown; the destination balance belongs to someone else."""

    transfer: TransferRead
    already_exists: bool
    source_balance: int
