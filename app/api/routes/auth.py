from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, session: SessionDep):
    return auth_service.register_user(session, body.email, body.password)


@router.post("/login", response_model=UserRead)
def login(body: LoginRequest, response: Response, session: SessionDep):
    user = auth_service.authenticate_user(session, body.email, body.password)
    response.set_cookie(
        key=settings.cookie_name,
        value=create_access_token(user.id),
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,  # not readable from JavaScript
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser):
    return current_user
