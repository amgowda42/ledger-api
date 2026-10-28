"""Domain errors. Each one maps to an HTTP status + a stable machine-readable code."""

from typing import Any


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal server error"

    def __init__(self, message: str | None = None, details: list[Any] | None = None):
        self.message = message or self.message
        self.details = details or []
        super().__init__(self.message)


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication required"


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid email or password"


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    code = "email_already_registered"
    message = "A user with this email already exists"


class AccountNotFoundError(AppError):
    # Also returned for someone else's account, so ids can't be probed.
    status_code = 404
    code = "account_not_found"
    message = "Account not found"


class AccountAlreadyExistsError(AppError):
    status_code = 409
    code = "account_already_exists"
    message = "You already have an account"


class InsufficientBalanceError(AppError):
    status_code = 422
    code = "insufficient_balance"
    message = "Insufficient balance for this debit"


class InvalidTransferError(AppError):
    status_code = 422
    code = "invalid_transfer"
    message = "Source and destination accounts must be different"
