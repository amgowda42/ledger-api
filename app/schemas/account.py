from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

AccountName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class AccountCreate(BaseModel):
    # extra="forbid": a client sending `balance` (or id / created_at) gets a 422
    # instead of having it silently ignored. Only `name` can be supplied.
    model_config = ConfigDict(extra="forbid")

    name: AccountName


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    balance: int
    created_at: datetime


class BalanceRead(BaseModel):
    account_id: int
    balance: int
