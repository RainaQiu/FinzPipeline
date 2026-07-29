# Finz Ledger Bridge

Finz Ledger Bridge imports bank CSV/XLSX data into an immutable internal
ledger, detects duplicates and transfers, applies deterministic accounting
rules, routes uncertain items to review, calculates cash-basis P&L, and prepares
idempotent QuickBooks Online (QBO) outbox items. QBO transaction execution is
intentionally disabled.

## Safe local start

Use Python 3.12 from the project root:

```powershell
& .\.venv312\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location backend
& ..\.venv312\Scripts\python.exe -m uvicorn app.main:app --reload
```

In another terminal:

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://localhost:5173`. The default repository is in memory. No QBO
transaction is created by any UI or API route.

## Tests

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest -q

Set-Location ..\frontend
pnpm test -- --run
pnpm build
```

The challenge workbook is covered by a golden integration test. Expected
results are 200 raw rows, 195 unique transactions, five duplicate extras, six
transfer pairs, and net profit of 6,818,000 cents.

## Local MongoDB

The local Docker service is authenticated, binds only to `127.0.0.1`, and uses
the named volume `finz_mongodb_data`. Setup, start/stop, authenticated ping,
index initialization, real repository tests, and persistence verification are
documented in [docs/local-mongodb.md](docs/local-mongodb.md).

Set `FINZ_REPOSITORY_BACKEND=mongo` only when the application process has a
valid `MONGODB_URI`. The checked-in `.env.example` contains placeholders only;
the ignored `.env` must never be printed, committed, or copied into logs.

## Safety boundaries

- Accounting amounts are integer cents or exact `Decimal`, never domain floats.
- Raw imports are immutable and retain source file/row hashes.
- Classification cannot change transaction amounts and must pass schema,
  account-whitelist, direction, confidence, and review checks. Transfer pairs
  must have equal-and-opposite legs; P&L arithmetic identities are verified.
- Reconciliation requires an exact $0.00 difference against a Cash/USD QBO
  report for the requested period.
- QBO sync endpoints create plan-only outbox items. Real transaction execution
  requires separate implementation review and explicit user authorization.
- A complete double-entry posting-plan/amount-conservation layer remains a
  prerequisite before enabling real QBO transaction writes.
- MongoDB Atlas and live QBO writes are not part of the verified local baseline.

Design and implementation documents live under `docs/superpowers/`.
