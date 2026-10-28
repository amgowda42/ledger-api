# Assumptions & Design Decisions

Where the assignment left something open, this is the choice that was made and why.
Anything marked **(extra)** goes beyond the assignment text.

## Users and authentication (extra)

The assignment does not ask for login. It was added so that each account has an owner.

- Users register with an email and a password (8 to 128 characters). Emails are compared
  case-insensitively. Passwords are hashed with argon2id.
- **One user has one account.** This is enforced by a unique index in the database, not
  only in the API.
- Login sets a JWT **access token** in an `HttpOnly` cookie (`SameSite=Lax`, 60 minutes by
  default). The server verifies signature and expiry on every request. The algorithm is
  pinned, so `alg: none` tokens are rejected. There is no refresh token.
- **Logout only clears the cookie.** A stateless access token cannot be revoked
  server-side, so a copied token stays valid until it expires. This is why the lifetime
  is short.
- Set `COOKIE_SECURE=true` when serving over HTTPS. Because the cookie is `SameSite=Lax`
  and all state-changing routes are `POST` with a JSON body, no separate CSRF token is used.
- Not implemented: rate limiting, account lockout, password reset, email verification, roles.

## Accounts

- `id` is an auto-increment integer.
- `balance` always starts at 0. A request that includes `balance` (or `id`, `created_at`)
  is **rejected with 422** instead of having the field silently ignored.
- `name` is required, trimmed, 1 to 100 characters.
- Accounts cannot be edited or deleted through the API.
- A user can only see and use their own account. Someone else's account returns **404**,
  identical to a missing account, so ids cannot be probed.

## Money

- Amounts are **whole numbers**, as in the assignment examples (50, 150, ...). They are
  stored as integers. `50.5`, `"50"` and `true` are rejected, so there is no floating-point
  rounding.
- Valid range: 1 to 1,000,000,000,000. The cap keeps balances far below SQLite's 64-bit
  integer limit.
- There is a single implicit currency.

## Transactions

- `description` is required (1 to 255 characters). `reference_id` is required, trimmed,
  1 to 100 characters.
- `reference_id` is unique **per account**. The same value may be used on different
  accounts.
- **Duplicates:** repeating a `reference_id` on the same account creates nothing and
  leaves the balance alone. The API answers **200** with the original transaction and
  `"already_exists": true` (a new transaction is **201**).
  - The original is returned even if the repeated request had a different amount or
    description. The payloads are not compared, so the client can see what was stored.
  - A retried debit that would now be insufficient is still reported as a duplicate,
    not as an error.
- **Insufficient balance** returns **422** (`insufficient_balance`). A debit of exactly
  the balance is allowed.
- Reference ids starting with `transfer:` (any case) are reserved for transfers and are
  rejected on this endpoint.
- Transactions are **immutable**. There are no edit or delete routes, and database
  triggers also abort any `UPDATE` or `DELETE` on the table. Corrections are made with a
  new offsetting transaction.

## Transaction history

- Sorted by `created_at` descending. Rows created at the same instant are ordered by `id`
  descending, so the order is stable.
- `type=credit|debit` filters. Without it both types are returned.
- `page` starts at 1 (maximum 1,000,000). `limit` defaults to 20 (range 1 to 100).
- A page past the end returns **200** with an empty list and the real totals. It is not
  an error. Invalid `page`, `limit` or `type` values return **422**.
- Response: `items` plus `pagination` with `page`, `limit`, `total_records`, `total_pages`
  (0 pages when there are no records).

## Atomicity and concurrency

- The balance change and the ledger row are written in **one database transaction**.
  If either fails, neither is saved.
- A debit is a single conditional statement (`UPDATE ... WHERE balance >= amount`), so two
  simultaneous debits cannot overdraw an account. A database `CHECK (balance >= 0)` is a
  second layer behind it.
- The unique `(account_id, reference_id)` constraint is the final guard against duplicates,
  so two identical requests arriving at once apply exactly once.
- **SQLite allows one writer at a time.** Writers queue (5 second wait). That is fine for
  this scope, but it is not a high-concurrency design. A server database would use the
  same statements.
- The balance is stored on the account, not recomputed from history. The tests check that
  the two always agree.

## Transfers (bonus, extra requirements marked)

- `POST /transfers` moves money from **your** account to **any existing** account.
  Both must exist (404 otherwise). Source and destination must differ (422).
- The debit, the credit, the transfer record and both ledger rows are committed together
  or not at all. A partial transfer is not possible. The tests force failures at several
  points to check this.
- **(extra)** `reference_id` is required and is the idempotency key, scoped to the sending
  account. A retry returns **200** with `already_exists: true` and moves nothing.
- `description` is optional and defaults to `"Transfer"`.
- Each transfer appears in both accounts' history as a debit row and a credit row, with
  reference ids `transfer:<id>:debit` and `transfer:<id>:credit`.
- The sender is told only their own resulting balance, not the recipient's.
- Because the destination can be any account, a 404 versus a success reveals whether an
  account id exists. This is unavoidable if people can send to each other by id.
- Balances are updated in ascending account-id order. SQLite does not need this, but it
  prevents deadlocks on databases with row locks.

## Errors

Every error uses one JSON shape: `{"error": {"code", "message", "details"}}`. Validation
errors list `in` (`body`, `query` or `path`), `field`, `message` and `type`. The submitted
value is never echoed back, because it could be a password. Codes are listed in the README.

## Data, time and storage

- Timestamps are UTC, ISO-8601 with a `Z` suffix.
- Tables are created on startup. There are **no migrations**. Adding a column to an
  existing table during development means deleting `ledger.db`. Adding a new table is
  picked up automatically.
- SQLite runs in WAL mode. **Keep the project and `ledger.db` on a local disk**, not a
  network share, because WAL is unreliable there.
- `JWT_SECRET_KEY` is required (32 characters or more). The app refuses to start without it.

## Not included

Refresh tokens, token revocation, rate limiting, password reset, multi-currency, decimal
amounts, refunds or reversals as a feature (use an offsetting transaction), a separate
endpoint to list transfers (they appear in transaction history), database migrations,
admin tools.
