from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime, utcnow


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    # Stored lower-cased by the service layer; unique at the DB level.
    email: str = Field(max_length=255, unique=True, index=True)
    hashed_password: str
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(UTCDateTime(), nullable=False)
    )
