from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.transfer import TransferCreate, TransferRead, TransferResult
from app.services import transfer_service

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post(
    "",
    response_model=TransferResult,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "reference_id already used by the source account; nothing moved"},
        404: {"description": "Source (not yours) or destination account not found"},
        422: {"description": "Validation error, same account, or insufficient balance"},
    },
)
def create_transfer(
    body: TransferCreate,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
):
    """Move money from your account to another account, atomically.

    The debit and the credit succeed together or not at all. Each side shows up in its
    account's history as a ledger row with reference `transfer:<id>:debit` or
    `transfer:<id>:credit`.
    """
    outcome = transfer_service.create_transfer(
        session,
        owner_id=current_user.id,
        source_account_id=body.source_account_id,
        destination_account_id=body.destination_account_id,
        amount=body.amount,
        description=body.description,
        reference_id=body.reference_id,
    )
    if outcome.already_exists:
        response.status_code = status.HTTP_200_OK
    return TransferResult(
        transfer=TransferRead.model_validate(outcome.transfer),
        already_exists=outcome.already_exists,
        source_balance=outcome.source_balance,
    )
