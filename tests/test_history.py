import math

import pytest

from tests.helpers import API, post_tx


def get_history(client, account_id, **params):
    return client.get(f"{API}/accounts/{account_id}/transactions", params=params)


@pytest.fixture
def seeded(alice, alice_account):
    """25 transactions: r1..r25, odd = credit 10, even = debit 1."""
    aid = alice_account["id"]
    for i in range(1, 26):
        kind, amount = ("credit", 10) if i % 2 else ("debit", 1)
        assert post_tx(alice, aid, kind, amount, f"r{i}").status_code == 201
    return alice, aid


def test_empty_history(alice, alice_account):
    body = get_history(alice, alice_account["id"]).json()
    assert body["items"] == []
    assert body["pagination"] == {"page": 1, "limit": 20, "total_records": 0, "total_pages": 0}


def test_latest_first(seeded):
    client, aid = seeded
    items = get_history(client, aid, limit=100).json()["items"]
    assert [i["reference_id"] for i in items] == [f"r{n}" for n in range(25, 0, -1)]
    stamps = [i["created_at"] for i in items]
    assert stamps == sorted(stamps, reverse=True)


def test_no_type_returns_both(seeded):
    client, aid = seeded
    body = get_history(client, aid, limit=100).json()
    assert {i["type"] for i in body["items"]} == {"credit", "debit"}
    assert body["pagination"]["total_records"] == 25


@pytest.mark.parametrize("kind, expected", [("credit", 13), ("debit", 12)])
def test_filter_by_type(seeded, kind, expected):
    client, aid = seeded
    body = get_history(client, aid, type=kind, limit=100).json()
    assert {i["type"] for i in body["items"]} == {kind}
    assert len(body["items"]) == body["pagination"]["total_records"] == expected


def test_pagination_metadata_and_pages(seeded):
    client, aid = seeded
    page1 = get_history(client, aid, page=1, limit=10).json()
    page2 = get_history(client, aid, page=2, limit=10).json()
    page3 = get_history(client, aid, page=3, limit=10).json()

    assert page1["pagination"] == {"page": 1, "limit": 10, "total_records": 25, "total_pages": 3}
    assert (len(page1["items"]), len(page2["items"]), len(page3["items"])) == (10, 10, 5)

    ids = [i["id"] for p in (page1, page2, page3) for i in p["items"]]
    assert len(set(ids)) == 25  # no overlap, no gaps
    assert ids == sorted(ids, reverse=True)  # still latest-first across pages


def test_default_page_and_limit(seeded):
    client, aid = seeded
    body = get_history(client, aid).json()
    assert body["pagination"] == {"page": 1, "limit": 20, "total_records": 25, "total_pages": 2}
    assert len(body["items"]) == 20


def test_page_past_the_end_is_empty_not_an_error(seeded):
    client, aid = seeded
    response = get_history(client, aid, page=4, limit=10)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["pagination"]["total_pages"] == 3


def test_filter_and_pagination_combine(seeded):
    client, aid = seeded
    body = get_history(client, aid, type="credit", page=2, limit=5).json()
    assert body["pagination"] == {
        "page": 2, "limit": 5, "total_records": 13, "total_pages": math.ceil(13 / 5),
    }
    assert len(body["items"]) == 5
    assert {i["type"] for i in body["items"]} == {"credit"}


@pytest.mark.parametrize(
    "params, field",
    [
        ({"page": 0}, "page"),
        ({"page": -1}, "page"),
        ({"page": "abc"}, "page"),
        ({"page": 1_000_001}, "page"),
        ({"limit": 0}, "limit"),
        ({"limit": -5}, "limit"),
        ({"limit": 101}, "limit"),
        ({"limit": "ten"}, "limit"),
        ({"type": "refund"}, "type"),
        ({"type": "CREDIT"}, "type"),
    ],
)
def test_invalid_query_parameters_are_422(alice, alice_account, params, field):
    response = get_history(alice, alice_account["id"], **params)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(d["field"] == field and d["in"] == "query" for d in error["details"])


def test_history_of_missing_account_is_404(alice, alice_account):
    response = get_history(alice, 9999)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"


def test_cannot_read_someone_elses_history(alice, alice_account, bob, bob_account):
    post_tx(bob, bob_account["id"], "credit", 10, "private")
    assert get_history(alice, bob_account["id"]).status_code == 404


def test_history_requires_login(client):
    assert get_history(client, 1).status_code == 401
