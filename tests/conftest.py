import os
import tempfile

# Must be set before the app (and its settings) are imported.
_tmp_dir = tempfile.mkdtemp(prefix="ledger-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir}/test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes-long"
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


@pytest.fixture
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def alice():
    """Signed-in client, no account yet."""
    from tests.helpers import sign_in

    return sign_in("alice.ledger@example.com")


@pytest.fixture
def bob():
    from tests.helpers import sign_in

    return sign_in("bob.ledger@example.com")


@pytest.fixture
def alice_account(alice):
    from tests.helpers import open_account

    return open_account(alice, "Alice")


@pytest.fixture
def bob_account(bob):
    from tests.helpers import open_account

    return open_account(bob, "Bob")


CREDENTIALS = {"email": "alice@example.com", "password": "correct-horse-battery"}
