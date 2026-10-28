from fastapi import APIRouter, status

from app.api.deps import AccountId, CurrentUser, SessionDep
from app.schemas.account import AccountCreate, AccountRead, BalanceRead
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate, session: SessionDep, current_user: CurrentUser):
    """Open your account. The balance always starts at 0 and cannot be supplied."""
    return account_service.create_account(session, current_user.id, body.name)


# Declared before "/{account_id}/..." so "me" is never parsed as an id.
@router.get("/me", response_model=AccountRead)
def get_my_account(session: SessionDep, current_user: CurrentUser):
    return account_service.get_account_of_owner(session, current_user.id)


@router.get("/{account_id}/balance", response_model=BalanceRead)
def get_balance(account_id: AccountId, session: SessionDep, current_user: CurrentUser):
    account = account_service.get_owned_account(session, account_id, current_user.id)
    return BalanceRead(account_id=account.id, balance=account.balance)
