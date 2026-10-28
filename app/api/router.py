from fastapi import APIRouter

from app.api.routes import accounts, auth, transactions, transfers

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)
api_router.include_router(transfers.router)
