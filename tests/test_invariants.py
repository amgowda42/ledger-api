"""After a chaotic concurrent workload, the books must still balance."""

import random
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import Session

from app.db.session import engine
from tests.helpers import clone_client, open_account, post_transfer, post_tx, sign_in


def rows(sql: str):
    # exec_driver_sql: the SQL contains 'transfer:...:debit' which text() would parse as binds
    with Session(engine) as session:
        return session.connection().exec_driver_sql(sql).all()


def test_ledger_invariants_hold_under_mixed_concurrent_load():
    rng = random.Random(20261028)  # fixed seed: the same workload every run
    users = [sign_in(f"load{i}@example.com") for i in range(3)]
    accounts = [open_account(u, f"Load {i}")["id"] for i, u in enumerate(users)]

    for i, (user, account) in enumerate(zip(users, accounts, strict=True)):
        assert post_tx(user, account, "credit", 100, f"seed-{i}").status_code == 201

    # 60 operations, some deliberately impossible (overdrafts) or repeated (duplicates).
    operations = []
    for n in range(60):
        who = rng.randrange(3)
        kind = rng.choice(["credit", "debit", "transfer", "transfer", "repeat"])
        amount = rng.choice([1, 5, 20, 50, 80, 150])
        if kind == "repeat":
            operations.append((who, "credit", amount, "fixed-ref", None))  # same ref every time
        elif kind == "transfer":
            dest = rng.choice([i for i in range(3) if i != who])
            operations.append((who, "transfer", amount, f"op-{n}", dest))
        else:
            operations.append((who, kind, amount, f"op-{n}", None))

    barrier = threading.Barrier(8)

    def run(op):
        who, kind, amount, ref, dest = op
        client = clone_client(users[who])
        try:
            barrier.wait(timeout=0.05)  # best effort: line the first wave up
        except threading.BrokenBarrierError:
            pass
        if kind == "transfer":
            return post_transfer(client, accounts[who], accounts[dest], amount, ref).status_code
        return post_tx(client, accounts[who], kind, amount, ref).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(run, operations))

    assert set(statuses) <= {200, 201, 422}, statuses  # no 500s, no lock errors
    assert 201 in statuses and 422 in statuses  # the workload really exercised both paths

    # 1. every balance equals the sum of that account's ledger rows, and is never negative
    mismatches = rows(
        """
        SELECT a.id, a.balance,
               COALESCE(SUM(CASE t.type WHEN 'credit' THEN t.amount ELSE -t.amount END), 0)
        FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id
        HAVING a.balance <> COALESCE(SUM(CASE t.type WHEN 'credit' THEN t.amount ELSE -t.amount END), 0)
            OR a.balance < 0
        """
    )
    assert mismatches == []

    # 2. transfers conserve money: total balance == external credits - external debits
    total_balance = rows("SELECT COALESCE(SUM(balance), 0) FROM accounts")[0][0]
    external_net = rows(
        """
        SELECT COALESCE(SUM(CASE type WHEN 'credit' THEN amount ELSE -amount END), 0)
        FROM transactions WHERE reference_id NOT LIKE 'transfer:%'
        """
    )[0][0]
    assert total_balance == external_net

    # 3. every transfer has exactly one debit leg and one credit leg, for its own amount
    broken = rows(
        """
        SELECT tr.id FROM transfers tr
        WHERE (SELECT COUNT(*) FROM transactions t
               WHERE t.reference_id = 'transfer:' || tr.id || ':debit'
                 AND t.account_id = tr.source_account_id AND t.type = 'debit'
                 AND t.amount = tr.amount) <> 1
           OR (SELECT COUNT(*) FROM transactions t
               WHERE t.reference_id = 'transfer:' || tr.id || ':credit'
                 AND t.account_id = tr.destination_account_id AND t.type = 'credit'
                 AND t.amount = tr.amount) <> 1
        """
    )
    assert broken == []
    leg_rows = rows("SELECT COUNT(*) FROM transactions WHERE reference_id LIKE 'transfer:%'")[0][0]
    assert leg_rows == 2 * rows("SELECT COUNT(*) FROM transfers")[0][0]  # no orphan legs

    # 4. the repeated 'fixed-ref' credit was applied at most once per account
    repeats = rows(
        "SELECT account_id, COUNT(*) FROM transactions WHERE reference_id = 'fixed-ref' GROUP BY account_id"
    )
    assert all(count == 1 for _, count in repeats)
