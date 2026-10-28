from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AccountId, CurrentUser, SessionDep
from app.models import TransactionType
from app.schemas.transaction import (
    Pagination,
    TransactionCreate,
    TransactionPage,
    TransactionRead,
    TransactionResult,
)
from app.services import account_service, transaction_service

router = APIRouter(prefix="/accounts/{account_id}/transactions", tags=["transactions"])

# Only POST and GET exist on purpose: transactions are immutable through the API.


@router.post(
    "",
    response_model=TransactionResult,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "reference_id already used for this account; nothing changed"},
        404: {"description": "Account not found"},
        422: {"description": "Validation error or insufficient balance"},
    },
)
def add_transaction(
    account_id: AccountId,
    body: TransactionCreate,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
):
    account_service.get_owned_account(session, account_id, current_user.id)
    outcome = transaction_service.create_transaction(
        session,
        account_id=account_id,
        tx_type=body.type,
        amount=body.amount,
        description=body.description,
        reference_id=body.reference_id,
    )
    if outcome.already_exists:
        response.status_code = status.HTTP_200_OK
    return TransactionResult(
        transaction=TransactionRead.model_validate(outcome.transaction),
        already_exists=outcome.already_exists,
        account_balance=outcome.account_balance,
    )


@router.get("", response_model=TransactionPage)
def list_transactions(
    account_id: AccountId,
    session: SessionDep,
    current_user: CurrentUser,
    tx_type: Annotated[
        TransactionType | None,
        Query(alias="type", description="credit or debit. Omit for both."),
    ] = None,
    page: Annotated[int, Query(ge=1, le=1_000_000, description="1-based page")] = 1,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size")] = 20,
):
    """Transactions for the account, latest first (by created_at)."""
    account_service.get_owned_account(session, account_id, current_user.id)
    items, total_records, total_pages = transaction_service.list_transactions(
        session, account_id, tx_type, page, limit
    )
    return TransactionPage(
        items=[TransactionRead.model_validate(item) for item in items],
        pagination=Pagination(
            page=page,
            limit=limit,
            total_records=total_records,
            total_pages=total_pages,
        ),
    )
