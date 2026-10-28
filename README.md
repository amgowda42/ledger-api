# Transaction Ledger API

A backend API for a simple transaction ledger: create an account, post credits and debits,
read the balance and the transaction history, and (bonus) transfer money between accounts.

**Stack:** Python 3.11+, FastAPI, SQLModel (SQLAlchemy) on SQLite, JWT in an HttpOnly cookie.

For the choices made where the assignment was open, see **[ASSUMPTIONS.md](ASSUMPTIONS.md)**.
Interactive API docs are served at `/docs` once the app is running, and an exported copy of
the OpenAPI spec is in [`docs/openapi.json`](docs/openapi.json).

## Quick Start

From the project folder, create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the packages and create your environment file:

```bash
pip install -r requirements.txt
cp .env.example .env
```

On Windows Command Prompt, use `copy .env.example .env` instead of `cp`.

Generate a random JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set `JWT_SECRET_KEY` in `.env` to the generated value, then start the app:

```bash
uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs> to explore and test the API.

## Features

- Accounts with a system-managed balance that always starts at 0.
- Credit and debit transactions with an exact balance check (no overdrafts).
- Idempotent transactions: the same `reference_id` on the same account is applied once.
- History with `type` filter, pagination metadata and latest-first ordering.
- Immutable ledger, enforced by the API (no edit/delete routes) and by database triggers.
- Atomic balance + ledger writes, with database constraints as a backstop.
- Bonus: atomic, idempotent money transfers.
- Cookie-based JWT authentication. Every account belongs to one user.

## Project layout

```
ledger-api/
├── app/
│   ├── main.py                  # app factory, lifespan, router registration
│   ├── api/
│   │   ├── deps.py              # session + current-user (cookie JWT) dependencies
│   │   ├── router.py
│   │   └── routes/              # auth.py, accounts.py, transactions.py, transfers.py
│   ├── core/
│   │   ├── config.py            # settings from environment / .env
│   │   ├── security.py          # password hashing, JWT create/verify
│   │   ├── exceptions.py        # domain errors -> status code + error code
│   │   └── error_handlers.py    # one consistent error envelope
│   ├── db/                      # engine + SQLite pragmas, UTC datetime type
│   ├── models/                  # SQLModel tables + constraints + triggers
│   ├── schemas/                 # request / response models (validation)
│   └── services/                # business logic (routes stay thin)
├── tests/                       # pytest suite
├── docs/openapi.json            # exported API spec
├── ASSUMPTIONS.md
├── requirements.txt
├── .env.example
└── pytest.ini
```

## Getting started

Requires Python 3.11 or newer. Keep the folder on a **local disk** (not a network drive):
SQLite's WAL mode and Python virtual environments both misbehave on network shares.

### 1. Create and activate a virtual environment

Run this from the project folder:

```bash
python -m venv .venv
```

Activate it using the command for your terminal:

```bash
# Linux / macOS
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```cmd
:: Windows Command Prompt
.venv\Scripts\activate
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

### 2. Install the packages

```bash
pip install -r requirements.txt
```

### 3. Configure the app

Copy the example environment file:

```bash
cp .env.example .env
```

For Windows Command Prompt, use:

```cmd
copy .env.example .env
```

Open `.env` and set `JWT_SECRET_KEY` to a new, random value. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated value into `.env`, for example:

```dotenv
JWT_SECRET_KEY=paste-your-generated-random-value-here
```

The app will not start until you replace the example text with the generated value.

### 4. Run the app

```bash
uvicorn app.main:app --reload
```

The database file `ledger.db` and its tables are created on first start.

### 5. Open the API docs and try a login

Go to <http://localhost:8000/docs>. In Swagger:

1. Expand `POST /api/v1/auth/register`, click **Try it out**, and register this demo user:

   ```json
   {"email": "demo@example.com", "password": "LedgerDemo123!"}
   ```

2. Expand `POST /api/v1/auth/login`, click **Try it out**, and submit the same email and
   password. The browser keeps the login cookie for the other API requests.
3. Try `POST /api/v1/accounts` with `{"name": "Main"}`. Then try `GET /api/v1/accounts/me`
   to check that the API is responding and your login works.

This is a local demo credential only. Choose your own credentials outside local testing.

**Run the tests** (they use a temporary database and do not touch `ledger.db`):

```bash
pytest
```

### Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET_KEY` | *required, 32+ chars* | Signing key for access tokens |
| `DATABASE_URL` | `sqlite:///./ledger.db` | Database location |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Token and cookie lifetime |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `COOKIE_NAME` | `access_token` | Name of the auth cookie |
| `COOKIE_SECURE` | `false` | Set `true` when served over HTTPS |
| `COOKIE_SAMESITE` | `lax` | `lax`, `strict` or `none` |

## Using the API

All routes are under `/api/v1`. Except register and login, they need the login cookie. In
Swagger (`/docs`) call `POST /auth/login` once and the browser keeps the cookie for you.

With curl (use `-c` to save the cookie, `-b` to send it):

```bash
B=http://localhost:8000/api/v1
H='content-type: application/json'

curl -X POST $B/auth/register -H "$H" -d '{"email":"me@example.com","password":"supersecret1"}'
curl -c jar.txt -X POST $B/auth/login -H "$H" -d '{"email":"me@example.com","password":"supersecret1"}'

curl -b jar.txt -X POST $B/accounts -H "$H" -d '{"name":"Main"}'
curl -b jar.txt -X POST $B/accounts/1/transactions -H "$H" \
  -d '{"type":"credit","amount":100,"description":"salary","reference_id":"pay-001"}'
curl -b jar.txt -X POST $B/accounts/1/transactions -H "$H" \
  -d '{"type":"debit","amount":30,"description":"rent","reference_id":"rent-001"}'
curl -b jar.txt $B/accounts/1/balance
curl -b jar.txt "$B/accounts/1/transactions?type=debit&page=1&limit=10"
```

### Endpoints

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/auth/register` | Create a user (`email`, `password`) | 201 |
| POST | `/auth/login` | Log in, sets the auth cookie | 200 |
| POST | `/auth/logout` | Clear the cookie | 204 |
| GET | `/auth/me` | Current user | 200 |
| POST | `/accounts` | Open your account (`name`) | 201 |
| GET | `/accounts/me` | Your account | 200 |
| GET | `/accounts/{id}/balance` | `{account_id, balance}` | 200 |
| POST | `/accounts/{id}/transactions` | Add a credit or debit | 201 (new), 200 (duplicate) |
| GET | `/accounts/{id}/transactions` | History: `type`, `page`, `limit` | 200 |
| POST | `/transfers` | Move money between accounts (bonus) | 201 (new), 200 (duplicate) |
| GET | `/health` | Liveness check (no auth, not under `/api/v1`) | 200 |

There are intentionally no `PUT`, `PATCH` or `DELETE` routes for transactions or transfers.

**Create account** `POST /accounts`: body `{"name": "Main"}`. Response:

```json
{"id": 1, "name": "Main", "balance": 0, "created_at": "2026-10-28T07:12:35.642167Z"}
```

Sending `balance` (or any other field) is rejected with 422.

**Add transaction** `POST /accounts/{id}/transactions`:

```json
{"type": "credit", "amount": 50, "description": "bonus", "reference_id": "bonus-001"}
```

```json
{
  "transaction": {"id": 2, "account_id": 1, "type": "credit", "amount": 50,
                  "description": "bonus", "reference_id": "bonus-001",
                  "created_at": "2026-10-28T07:12:35.668831Z"},
  "already_exists": false,
  "account_balance": 150
}
```

Sending the same `reference_id` again for the same account returns **200** with the same
transaction, `"already_exists": true`, and the balance unchanged.

**History** `GET /accounts/{id}/transactions?type=&page=&limit=` returns:

```json
{
  "items": [{"id": 3, "account_id": 1, "type": "debit", "amount": 30, "...": "..."}],
  "pagination": {"page": 1, "limit": 20, "total_records": 3, "total_pages": 1}
}
```

Newest first. `type` is `credit` or `debit` (omit for both). `limit` is 1 to 100.

**Transfer** `POST /transfers`:

```json
{"source_account_id": 1, "destination_account_id": 2, "amount": 30,
 "reference_id": "xfer-001", "description": "rent share"}
```

The source must be your account. The response is `{"transfer": {...}, "already_exists":
false, "source_balance": 70}`. Each transfer shows up as a debit and a credit in the two
accounts' histories.

### Errors

Every error has the same shape:

```json
{"error": {"code": "insufficient_balance", "message": "Insufficient balance for this debit", "details": []}}
```

| Status | `code` | When |
|---|---|---|
| 401 | `not_authenticated` | Missing, invalid or expired cookie |
| 401 | `invalid_credentials` | Wrong email or password |
| 404 | `account_not_found` | No such account, or it is not yours (or the transfer destination is missing) |
| 404 / 405 | `not_found` / `method_not_allowed` | Unknown route or method |
| 409 | `email_already_registered` | Email is taken |
| 409 | `account_already_exists` | You already have an account |
| 422 | `validation_error` | Bad body, query or path value (`details` lists each problem) |
| 422 | `insufficient_balance` | Debit or transfer larger than the balance |
| 422 | `invalid_transfer` | Source and destination are the same account |
| 500 | `internal_error` | Unexpected failure (nothing is partially saved) |

## How data integrity is kept

- **Atomic:** the balance update and the ledger row are one database transaction. A failure
  anywhere rolls both back. A transfer's debit, credit and two ledger rows are likewise
  all-or-nothing.
- **No overdraft, even under load:** a debit is one conditional SQL statement
  (`... WHERE balance >= amount`), not a read followed by a write. `CHECK (balance >= 0)`
  is a second layer.
- **No duplicate application:** a unique `(account_id, reference_id)` constraint decides, so
  simultaneous identical requests apply once.
- **Immutable:** no routes to change transactions, plus triggers that abort `UPDATE` and
  `DELETE` on the transactions and transfers tables.
- **Consistent:** the stored balance always equals credits minus debits for the account.
  The tests verify this after a mixed concurrent workload.

## Tests

`pytest` runs 169 tests covering:

- the rules in the assignment (credit, debit, insufficient balance, duplicates across and
  within accounts, filtering, pagination, ordering, validation, error responses);
- authentication (forged, expired, unsigned and tampered tokens) and account ownership;
- database constraints on their own, without the API;
- atomicity, by forcing failures part-way through a transaction and a transfer;
- concurrency (simultaneous debits, simultaneous duplicates, transfers in opposite
  directions) and a ledger-wide invariant check afterwards.

## Known limitations

SQLite allows a single writer at a time, tokens cannot be revoked before they expire, and
there are no migrations or rate limiting. See [ASSUMPTIONS.md](ASSUMPTIONS.md) for the full list.
