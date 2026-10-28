from fastapi.testclient import TestClient

from app.main import app

API = "/api/v1"
PASSWORD = "correct-horse-battery"


def sign_in(email: str) -> TestClient:
    """A fresh client (own cookie jar) registered and logged in as `email`."""
    client = TestClient(app)
    credentials = {"email": email, "password": PASSWORD}
    assert client.post(f"{API}/auth/register", json=credentials).status_code == 201
    assert client.post(f"{API}/auth/login", json=credentials).status_code == 200
    return client


def open_account(client: TestClient, name: str = "Main") -> dict:
    response = client.post(f"{API}/accounts", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def post_tx(
    client: TestClient,
    account_id: int,
    type: str,
    amount: int,
    reference_id: str,
    description: str = "test",
):
    return client.post(
        f"{API}/accounts/{account_id}/transactions",
        json={
            "type": type,
            "amount": amount,
            "description": description,
            "reference_id": reference_id,
        },
    )


def balance_of(client: TestClient, account_id: int) -> int:
    response = client.get(f"{API}/accounts/{account_id}/balance")
    assert response.status_code == 200, response.text
    return response.json()["balance"]


def post_transfer(client: TestClient, source: int, destination: int, amount: int, reference_id: str, **extra):
    payload = {
        "source_account_id": source,
        "destination_account_id": destination,
        "amount": amount,
        "reference_id": reference_id,
        **extra,
    }
    return client.post(f"{API}/transfers", json=payload)


def clone_client(client: TestClient) -> TestClient:
    """A new client (own connection state) carrying the same login cookie.
    TestClient instances are not shared between threads."""
    from app.core.config import settings

    clone = TestClient(app)
    clone.cookies.set(settings.cookie_name, client.cookies.get(settings.cookie_name))
    return clone


def db_scalar(sql: str, **params):
    """Read straight from the database, bypassing the API."""
    from sqlalchemy import text
    from sqlmodel import Session

    from app.db.session import engine

    with Session(engine) as session:
        return session.execute(text(sql), params).scalar_one()


def db_exec(sql: str) -> None:
    """Run raw SQL (e.g. CREATE TRIGGER) exactly as written. exec_driver_sql skips
    SQLAlchemy's ':name' bind-parameter parsing, which would mangle strings like
    'transfer:%:credit'."""
    from sqlmodel import Session

    from app.db.session import engine

    with Session(engine) as session:
        session.connection().exec_driver_sql(sql)
        session.commit()
