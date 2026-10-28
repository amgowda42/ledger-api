import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.db.session import engine
from app.main import app
from tests.helpers import API, balance_of, post_tx


def history(client, account_id, **params):
    response = client.get(f"{API}/accounts/{account_id}/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- credit / debit rules -----------------------------------------------------


def test_credit_increases_balance(alice, alice_account):
    aid = alice_account["id"]
    assert post_tx(alice, aid, "credit", 100, "c-1").status_code == 201
    response = post_tx(alice, aid, "credit", 50, "c-2")  # spec: 100 + 50 -> 150
    assert response.status_code == 201
    body = response.json()
    assert body["already_exists"] is False
    assert body["account_balance"] == 150
    assert balance_of(alice, aid) == 150


def test_transaction_has_all_spec_fields(alice, alice_account):
    aid = alice_account["id"]
    tx = post_tx(alice, aid, "credit", 40, "ref-x", description="salary").json()["transaction"]
    assert set(tx) == {"id", "account_id", "type", "amount", "description", "reference_id", "created_at"}
    assert tx["account_id"] == aid
    assert tx["type"] == "credit"
    assert tx["amount"] == 40
    assert tx["description"] == "salary"
    assert tx["reference_id"] == "ref-x"
    assert tx["created_at"].endswith("Z")


def test_debit_decreases_balance(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "c-1")
    response = post_tx(alice, aid, "debit", 30, "d-1")  # spec: 100 - 30 -> 70
    assert response.status_code == 201
    assert response.json()["account_balance"] == 70


def test_debit_with_insufficient_balance_is_rejected(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "c-1")
    response = post_tx(alice, aid, "debit", 150, "d-1")  # spec: 100 - 150 -> rejected
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert balance_of(alice, aid) == 100  # unchanged
    assert history(alice, aid)["pagination"]["total_records"] == 1  # nothing recorded


def test_debit_of_exact_balance_is_allowed(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "c-1")
    assert post_tx(alice, aid, "debit", 100, "d-1").status_code == 201
    assert balance_of(alice, aid) == 0


def test_debit_on_empty_account_is_rejected(alice, alice_account):
    response = post_tx(alice, alice_account["id"], "debit", 1, "d-1")
    assert response.status_code == 422
    assert balance_of(alice, alice_account["id"]) == 0


def test_balance_equals_sum_of_valid_transactions(alice, alice_account):
    """Spec example: 0 +100 +50 -30 -20 = 100, with a rejected debit in between."""
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "r1")
    post_tx(alice, aid, "credit", 50, "r2")
    post_tx(alice, aid, "debit", 30, "r3")
    assert post_tx(alice, aid, "debit", 10_000, "rejected").status_code == 422
    post_tx(alice, aid, "debit", 20, "r4")
    assert balance_of(alice, aid) == 100

    items = history(alice, aid, limit=100)["items"]
    signed = [i["amount"] if i["type"] == "credit" else -i["amount"] for i in items]
    assert sum(signed) == 100 == balance_of(alice, aid)


# --- duplicates / idempotency -----------------------------------------------------


def test_duplicate_reference_creates_nothing_and_changes_nothing(alice, alice_account):
    aid = alice_account["id"]
    first = post_tx(alice, aid, "credit", 50, "same-ref")
    assert first.status_code == 201

    again = post_tx(alice, aid, "credit", 50, "same-ref")
    assert again.status_code == 200
    body = again.json()
    assert body["already_exists"] is True
    assert body["transaction"]["id"] == first.json()["transaction"]["id"]
    assert body["account_balance"] == 50
    assert balance_of(alice, aid) == 50
    assert history(alice, aid)["pagination"]["total_records"] == 1


def test_duplicate_returns_original_even_if_payload_differs(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 50, "same-ref", description="original")
    again = post_tx(alice, aid, "credit", 999, "same-ref", description="changed")
    assert again.status_code == 200
    assert again.json()["transaction"]["amount"] == 50
    assert again.json()["transaction"]["description"] == "original"
    assert balance_of(alice, aid) == 50


def test_retried_debit_is_a_duplicate_not_insufficient_balance(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "c-1")
    assert post_tx(alice, aid, "debit", 100, "d-1").status_code == 201
    # balance is now 0, so a *new* 100 debit would fail, but a retry must not
    retry = post_tx(alice, aid, "debit", 100, "d-1")
    assert retry.status_code == 200
    assert retry.json()["already_exists"] is True
    assert balance_of(alice, aid) == 0


def test_same_reference_is_allowed_on_different_accounts(alice, alice_account, bob, bob_account):
    a = post_tx(alice, alice_account["id"], "credit", 10, "shared-ref")
    b = post_tx(bob, bob_account["id"], "credit", 20, "shared-ref")
    assert a.status_code == b.status_code == 201
    assert a.json()["already_exists"] is b.json()["already_exists"] is False
    assert balance_of(alice, alice_account["id"]) == 10
    assert balance_of(bob, bob_account["id"]) == 20


def test_reference_is_trimmed_before_comparing(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 5, "ref-1")
    assert post_tx(alice, aid, "credit", 5, "  ref-1  ").status_code == 200
    assert balance_of(alice, aid) == 5


# --- validation ----------------------------------------------------------------


def body(**overrides):
    data = {"type": "credit", "amount": 10, "description": "d", "reference_id": "r"}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not ...}


@pytest.mark.parametrize(
    "payload, bad_field",
    [
        (body(type="refund"), "type"),
        (body(type="CREDIT"), "type"),
        (body(type=None), "type"),
        (body(type=...), "type"),
        (body(amount=0), "amount"),
        (body(amount=-5), "amount"),
        (body(amount=1.5), "amount"),
        (body(amount=50.0), "amount"),
        (body(amount="50"), "amount"),
        (body(amount=True), "amount"),
        (body(amount=None), "amount"),
        (body(amount=...), "amount"),
        (body(amount=1_000_000_000_001), "amount"),
        (body(reference_id=...), "reference_id"),
        (body(reference_id=""), "reference_id"),
        (body(reference_id="   "), "reference_id"),
        (body(reference_id="x" * 101), "reference_id"),
        (body(description=...), "description"),
        (body(description=""), "description"),
        (body(description="x" * 256), "description"),
    ],
)
def test_invalid_input_is_rejected_and_changes_nothing(alice, alice_account, payload, bad_field):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "seed")
    response = alice.post(f"{API}/accounts/{aid}/transactions", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert bad_field in {d["field"] for d in error["details"]}
    assert balance_of(alice, aid) == 100
    assert history(alice, aid)["pagination"]["total_records"] == 1


def test_unknown_fields_are_rejected(alice, alice_account):
    aid = alice_account["id"]
    response = alice.post(f"{API}/accounts/{aid}/transactions", json=body(created_at="2000-01-01T00:00:00Z"))
    assert response.status_code == 422
    assert balance_of(alice, aid) == 0


def test_malformed_json_body_is_a_422_envelope(alice, alice_account):
    response = alice.post(
        f"{API}/accounts/{alice_account['id']}/transactions",
        content="{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_missing_account_is_404(alice, alice_account):
    response = post_tx(alice, 9999, "credit", 10, "r")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"


def test_cannot_transact_on_someone_elses_account(alice, alice_account, bob, bob_account):
    response = post_tx(alice, bob_account["id"], "credit", 1000, "steal")
    assert response.status_code == 404
    assert balance_of(bob, bob_account["id"]) == 0
    assert history(bob, bob_account["id"])["pagination"]["total_records"] == 0


def test_requires_login_even_with_an_invalid_body(client):
    assert post_tx(client, 1, "credit", 10, "r").status_code == 401
    assert client.post(f"{API}/accounts/1/transactions", json={}).status_code == 401


# --- immutability through the API --------------------------------------------------


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_no_edit_or_delete_routes(alice, alice_account, method):
    aid = alice_account["id"]
    tx_id = post_tx(alice, aid, "credit", 10, "r").json()["transaction"]["id"]
    collection = f"{API}/accounts/{aid}/transactions"
    assert getattr(alice, method)(collection).status_code == 405
    assert getattr(alice, method)(f"{collection}/{tx_id}").status_code in (404, 405)
    # untouched
    assert history(alice, aid)["items"][0]["amount"] == 10


# --- atomicity ---------------------------------------------------------------------


def test_failed_insert_rolls_back_the_balance_change(alice, alice_account):
    """Force the ledger INSERT to fail after the balance UPDATE has run."""
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "seed")

    with Session(engine) as s:
        s.exec(text(
            "CREATE TRIGGER boom BEFORE INSERT ON transactions "
            "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        ))
        s.commit()

    try:
        quiet = TestClient(app, raise_server_exceptions=False)
        quiet.cookies.set(settings.cookie_name, alice.cookies.get(settings.cookie_name))
        response = post_tx(quiet, aid, "credit", 40, "will-fail")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
    finally:
        with Session(engine) as s:
            s.exec(text("DROP TRIGGER boom"))
            s.commit()

    assert balance_of(alice, aid) == 100  # the +40 was rolled back with the failed insert
    assert history(alice, aid)["pagination"]["total_records"] == 1


# --- concurrency -----------------------------------------------------------------


def clones(client, n):
    token = client.cookies.get(settings.cookie_name)
    result = []
    for _ in range(n):
        c = TestClient(app)
        c.cookies.set(settings.cookie_name, token)
        result.append(c)
    return result


def test_concurrent_debits_never_overdraw(alice, alice_account):
    aid = alice_account["id"]
    post_tx(alice, aid, "credit", 100, "seed")
    workers = clones(alice, 10)
    barrier = threading.Barrier(len(workers))

    def attempt(args):
        i, c = args
        barrier.wait()
        return post_tx(c, aid, "debit", 30, f"race-{i}").status_code

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        statuses = list(pool.map(attempt, enumerate(workers)))

    assert sorted(statuses) == [201] * 3 + [422] * 7  # 100 // 30 = 3 debits fit
    assert balance_of(alice, aid) == 10
    assert history(alice, aid)["pagination"]["total_records"] == 1 + 3


def test_concurrent_duplicate_requests_apply_exactly_once(alice, alice_account):
    aid = alice_account["id"]
    workers = clones(alice, 8)
    barrier = threading.Barrier(len(workers))

    def attempt(c):
        barrier.wait()
        return post_tx(c, aid, "credit", 50, "one-and-only")

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        responses = list(pool.map(attempt, workers))

    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert len({r.json()["transaction"]["id"] for r in responses}) == 1
    assert balance_of(alice, aid) == 50  # credited once, not eight times
    assert history(alice, aid)["pagination"]["total_records"] == 1
