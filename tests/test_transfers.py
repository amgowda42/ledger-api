import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import (
    API,
    balance_of,
    clone_client,
    db_exec,
    db_scalar,
    post_transfer,
    post_tx,
)


@pytest.fixture
def funded(alice, alice_account, bob, bob_account):
    """Alice has 100, Bob has 50 (the spec's example). Alice's account is created first,
    so alice id < bob id."""
    assert alice_account["id"] < bob_account["id"]
    post_tx(alice, alice_account["id"], "credit", 100, "seed")
    post_tx(bob, bob_account["id"], "credit", 50, "seed")
    return alice, alice_account["id"], bob, bob_account["id"]


def history(client, account_id, **params):
    response = client.get(f"{API}/accounts/{account_id}/transactions", params={"limit": 100, **params})
    assert response.status_code == 200
    return response.json()["items"]


def transfer_count() -> int:
    return db_scalar("SELECT COUNT(*) FROM transfers")


def ledger_count() -> int:
    return db_scalar("SELECT COUNT(*) FROM transactions")


# --- the happy path --------------------------------------------------------------


def test_spec_example_a100_b50_transfer_30(funded):
    alice, a, bob, b = funded
    response = post_transfer(alice, a, b, 30, "t-1", description="rent share")
    assert response.status_code == 201
    body = response.json()
    assert body["already_exists"] is False
    assert body["source_balance"] == 70
    assert body["transfer"]["amount"] == 30
    assert body["transfer"]["source_account_id"] == a
    assert body["transfer"]["destination_account_id"] == b
    assert body["transfer"]["description"] == "rent share"
    assert balance_of(alice, a) == 70
    assert balance_of(bob, b) == 80


def test_transfer_writes_a_debit_and_a_credit_ledger_row(funded):
    alice, a, bob, b = funded
    transfer_id = post_transfer(alice, a, b, 30, "t-1").json()["transfer"]["id"]

    debit = history(alice, a)[0]
    credit = history(bob, b)[0]
    assert (debit["type"], debit["amount"], debit["reference_id"]) == ("debit", 30, f"transfer:{transfer_id}:debit")
    assert (credit["type"], credit["amount"], credit["reference_id"]) == ("credit", 30, f"transfer:{transfer_id}:credit")


def test_default_description(funded):
    alice, a, _, b = funded
    assert post_transfer(alice, a, b, 5, "t-1").json()["transfer"]["description"] == "Transfer"


def test_transfer_of_the_whole_balance_is_allowed(funded):
    alice, a, bob, b = funded
    assert post_transfer(alice, a, b, 100, "t-1").status_code == 201
    assert balance_of(alice, a) == 0
    assert balance_of(bob, b) == 150


def test_transfer_works_in_both_directions(funded):
    alice, a, bob, b = funded
    assert post_transfer(bob, b, a, 20, "t-1").status_code == 201  # higher id -> lower id
    assert balance_of(alice, a) == 120
    assert balance_of(bob, b) == 30


# --- rejected transfers leave no trace ------------------------------------------------


def test_insufficient_balance_moves_nothing(funded):
    alice, a, bob, b = funded
    before = (transfer_count(), ledger_count())
    response = post_transfer(alice, a, b, 150, "t-1")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert (balance_of(alice, a), balance_of(bob, b)) == (100, 50)
    assert (transfer_count(), ledger_count()) == before


def test_same_account_is_rejected(funded):
    alice, a, _, _ = funded
    response = post_transfer(alice, a, a, 10, "t-1")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_transfer"
    assert balance_of(alice, a) == 100


def test_missing_destination_is_404_and_source_untouched(funded):
    alice, a, _, _ = funded
    response = post_transfer(alice, a, 9999, 10, "t-1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"
    assert response.json()["error"]["message"] == "Destination account not found"
    assert balance_of(alice, a) == 100
    assert transfer_count() == 0


def test_missing_source_is_404(funded):
    alice, _, _, b = funded
    response = post_transfer(alice, 9999, b, 10, "t-1")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Source account not found"


def test_cannot_send_from_someone_elses_account(funded):
    alice, a, bob, b = funded
    response = post_transfer(alice, b, a, 40, "steal")  # alice tries to drain bob
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Source account not found"
    assert (balance_of(alice, a), balance_of(bob, b)) == (100, 50)
    assert transfer_count() == 0


def test_requires_login(client):
    assert post_transfer(client, 1, 2, 10, "t-1").status_code == 401
    assert client.post(f"{API}/transfers", json={}).status_code == 401


def valid(**overrides):
    data = {"source_account_id": 1, "destination_account_id": 2, "amount": 10, "reference_id": "r"}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not ...}


@pytest.mark.parametrize(
    "payload, bad_field",
    [
        (valid(amount=0), "amount"),
        (valid(amount=-1), "amount"),
        (valid(amount=1.5), "amount"),
        (valid(amount="10"), "amount"),
        (valid(amount=True), "amount"),
        (valid(amount=...), "amount"),
        (valid(source_account_id=0), "source_account_id"),
        (valid(source_account_id="1"), "source_account_id"),
        (valid(source_account_id=...), "source_account_id"),
        (valid(destination_account_id=-3), "destination_account_id"),
        (valid(destination_account_id=1.5), "destination_account_id"),
        (valid(destination_account_id=...), "destination_account_id"),
        (valid(reference_id=...), "reference_id"),
        (valid(reference_id="  "), "reference_id"),
        (valid(description=""), "description"),
        (valid(owner_id=1), "owner_id"),
    ],
)
def test_invalid_input_is_422_and_moves_nothing(funded, payload, bad_field):
    alice, a, bob, b = funded
    payload = {**payload}
    # point the structurally-valid ids at real accounts so only `bad_field` is wrong
    if payload.get("source_account_id") == 1:
        payload["source_account_id"] = a
    if payload.get("destination_account_id") == 2:
        payload["destination_account_id"] = b
    response = alice.post(f"{API}/transfers", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert bad_field in {d["field"] for d in error["details"]}
    assert (balance_of(alice, a), balance_of(bob, b)) == (100, 50)
    assert transfer_count() == 0


# --- idempotency -----------------------------------------------------------------


def test_duplicate_transfer_moves_nothing_twice(funded):
    alice, a, bob, b = funded
    first = post_transfer(alice, a, b, 30, "same")
    again = post_transfer(alice, a, b, 30, "same")
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["already_exists"] is True
    assert again.json()["transfer"]["id"] == first.json()["transfer"]["id"]
    assert again.json()["source_balance"] == 70
    assert (balance_of(alice, a), balance_of(bob, b)) == (70, 80)
    assert transfer_count() == 1
    assert ledger_count() == 2 + 2  # two seeds + two legs


def test_retry_is_a_duplicate_even_when_it_would_now_be_insufficient(funded):
    alice, a, _, b = funded
    assert post_transfer(alice, a, b, 100, "same").status_code == 201
    retry = post_transfer(alice, a, b, 100, "same")  # balance is 0 now
    assert retry.status_code == 200
    assert retry.json()["already_exists"] is True


def test_same_reference_from_a_different_sender_is_independent(funded):
    alice, a, bob, b = funded
    assert post_transfer(alice, a, b, 10, "shared").status_code == 201
    assert post_transfer(bob, b, a, 5, "shared").status_code == 201
    assert transfer_count() == 2


def test_transfer_reference_does_not_clash_with_transaction_reference(funded):
    alice, a, _, b = funded
    assert post_tx(alice, a, "credit", 1, "shared").status_code == 201
    assert post_transfer(alice, a, b, 10, "shared").status_code == 201


@pytest.mark.parametrize("reference", ["transfer:1:credit", "TRANSFER:7:debit", "transfer:anything"])
def test_clients_cannot_use_the_reserved_ledger_prefix(funded, reference):
    alice, a, _, _ = funded
    response = post_tx(alice, a, "credit", 10, reference)
    assert response.status_code == 422
    assert "reference_id" in {d["field"] for d in response.json()["error"]["details"]}
    assert balance_of(alice, a) == 100


# --- atomicity: a failure part-way through must undo everything ------------------------


def test_failure_on_the_second_ledger_row_rolls_back_both_balances_and_the_transfer(funded):
    alice, a, bob, b = funded
    ledger_before = ledger_count()
    db_exec(
        "CREATE TRIGGER boom BEFORE INSERT ON transactions "
        "WHEN NEW.reference_id LIKE 'transfer:%:credit' "
        "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
    )
    try:
        quiet = clone_client(alice)
        quiet = TestClient(app, raise_server_exceptions=False, cookies=quiet.cookies)
        response = post_transfer(quiet, a, b, 30, "will-fail")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
    finally:
        db_exec("DROP TRIGGER boom")

    assert (balance_of(alice, a), balance_of(bob, b)) == (100, 50)
    assert transfer_count() == 0
    assert ledger_count() == ledger_before  # the already-inserted debit row is gone too


@pytest.mark.parametrize("sender", ["alice", "bob"])
def test_failure_after_the_first_balance_update_rolls_it_back(funded, sender):
    """Bob's account (the higher id) is always updated second. Make that update fail
    after the first account has already been changed, in both directions."""
    alice, a, bob, b = funded
    db_exec(
        f"CREATE TRIGGER boom BEFORE UPDATE ON accounts WHEN NEW.id = {int(b)} "
        "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
    )
    try:
        client, source, destination = (alice, a, b) if sender == "alice" else (bob, b, a)
        quiet = TestClient(app, raise_server_exceptions=False, cookies=clone_client(client).cookies)
        response = post_transfer(quiet, source, destination, 20, "will-fail")
        assert response.status_code == 500
    finally:
        db_exec("DROP TRIGGER boom")

    assert (balance_of(alice, a), balance_of(bob, b)) == (100, 50)
    assert transfer_count() == 0


# --- concurrency -----------------------------------------------------------------


def run_concurrently(jobs):
    barrier = threading.Barrier(len(jobs))

    def run(job):
        barrier.wait()
        return job()

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(run, jobs))


def test_concurrent_transfers_never_overdraw_the_source(funded):
    alice, a, bob, b = funded
    jobs = [
        (lambda i=i: post_transfer(clone_client(alice), a, b, 30, f"race-{i}").status_code)
        for i in range(10)
    ]
    statuses = run_concurrently(jobs)
    assert sorted(statuses) == [201] * 3 + [422] * 7  # 100 // 30 fit
    assert balance_of(alice, a) == 10
    assert balance_of(bob, b) == 50 + 90
    assert transfer_count() == 3


def test_opposite_direction_transfers_do_not_deadlock_and_conserve_money(funded):
    alice, a, bob, b = funded
    post_tx(alice, a, "credit", 100, "top-up-a")  # 200 / 50 -> make both comfortably funded
    post_tx(bob, b, "credit", 150, "top-up-b")  # 200 / 200
    jobs = [(lambda i=i: post_transfer(clone_client(alice), a, b, 10, f"ab-{i}").status_code) for i in range(10)]
    jobs += [(lambda i=i: post_transfer(clone_client(bob), b, a, 10, f"ba-{i}").status_code) for i in range(10)]
    statuses = run_concurrently(jobs)
    assert statuses.count(201) == 20
    assert (balance_of(alice, a), balance_of(bob, b)) == (200, 200)
    assert balance_of(alice, a) + balance_of(bob, b) == 400  # money neither created nor lost
    assert transfer_count() == 20


def test_concurrent_identical_transfers_apply_exactly_once(funded):
    alice, a, bob, b = funded
    jobs = [(lambda: post_transfer(clone_client(alice), a, b, 30, "one-and-only")) for _ in range(8)]
    responses = run_concurrently(jobs)
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert len({r.json()["transfer"]["id"] for r in responses}) == 1
    assert (balance_of(alice, a), balance_of(bob, b)) == (70, 80)
    assert transfer_count() == 1
    assert ledger_count() == 2 + 2
