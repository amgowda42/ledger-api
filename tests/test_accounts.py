import pytest

from tests.helpers import API, balance_of, open_account


def test_create_account_starts_at_zero(alice):
    response = alice.post(f"{API}/accounts", json={"name": "  Alice Main  "})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alice Main"  # whitespace trimmed
    assert body["balance"] == 0
    assert isinstance(body["id"], int)
    assert body["created_at"].endswith("Z")  # system-generated, UTC
    assert "owner_id" not in body


@pytest.mark.parametrize("extra", [{"balance": 500}, {"id": 99}, {"created_at": "2020-01-01T00:00:00Z"}])
def test_client_cannot_set_system_fields(alice, extra):
    response = alice.post(f"{API}/accounts", json={"name": "Alice", **extra})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["in"] == "body"
    # and nothing was created
    assert alice.get(f"{API}/accounts/me").status_code == 404


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}, {"name": None}, {"name": "x" * 101}])
def test_name_is_required(alice, payload):
    response = alice.post(f"{API}/accounts", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "name"


def test_second_account_for_same_user_is_409(alice, alice_account):
    response = alice.post(f"{API}/accounts", json={"name": "Another"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_already_exists"


def test_get_my_account(alice, alice_account):
    response = alice.get(f"{API}/accounts/me")
    assert response.status_code == 200
    assert response.json() == alice_account


def test_get_my_account_before_creating_one_is_404(alice):
    response = alice.get(f"{API}/accounts/me")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"


def test_balance_response_shape(alice, alice_account):
    response = alice.get(f"{API}/accounts/{alice_account['id']}/balance")
    assert response.status_code == 200
    assert response.json() == {"account_id": alice_account["id"], "balance": 0}


def test_balance_of_missing_account_is_404(alice, alice_account):
    response = alice.get(f"{API}/accounts/9999/balance")
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "account_not_found",
        "message": "Account not found",
        "details": [],
    }


def test_other_users_account_looks_like_it_does_not_exist(alice, bob_account):
    missing = alice.get(f"{API}/accounts/9999/balance")
    foreign = alice.get(f"{API}/accounts/{bob_account['id']}/balance")
    assert foreign.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "1.5", "99999999999999999999"])
def test_invalid_account_id_is_422(alice, alice_account, bad_id):
    response = alice.get(f"{API}/accounts/{bad_id}/balance")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["in"] == "path"


def test_account_endpoints_require_login(client):
    assert client.post(f"{API}/accounts", json={"name": "X"}).status_code == 401
    assert client.get(f"{API}/accounts/me").status_code == 401
    assert client.get(f"{API}/accounts/1/balance").status_code == 401


def test_each_user_has_their_own_account(alice, bob):
    a = open_account(alice, "Alice")
    b = open_account(bob, "Bob")
    assert a["id"] != b["id"]
    assert balance_of(alice, a["id"]) == balance_of(bob, b["id"]) == 0
