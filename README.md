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

## Public Render demo

The public challenge demo runs as one Render Web Service: Render builds the
React app, then FastAPI serves its built files and the existing relative
`/api/v1/...` endpoints from the same HTTPS origin. Browser deep links such as
`/review` return the SPA; API, health, readiness, and documentation routes
remain backend routes.

Create the service from `render.yaml`, then set these values manually in the
Render dashboard (they are deliberately not stored in the blueprint):

- `APP_BASE_URL` to the service's HTTPS URL.
- `MONGODB_URI` and `MONGODB_DATABASE` for a non-placeholder Mongo database.
- Sandbox-only `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, and `QBO_REDIRECT_URI`
  (the redirect is `<APP_BASE_URL>/api/v1/integrations/qbo/callback`).
- `FINZ_DEMO_RESET_SECRET` to a dedicated random value used only by the weekly
  shared-workspace reset. Do not reuse the interviewer access code.

The blueprint explicitly selects Render's free plan, so the service may sleep
when idle and its first request after sleeping may be slow. It also selects the
Mongo repository backend; production will remain unavailable until a valid
Atlas URI is configured.

Production refuses to start with the in-memory repository, placeholder Mongo
settings, non-sandbox QBO, missing QBO settings, a non-HTTPS public URL, or a
missing frontend build. `/health` is liveness; `/ready` reports dependency
readiness and does not expose connection details. This is a shared
demonstration environment: do not upload sensitive or real financial data.
Authentication, tenant isolation, and per-user data separation are
intentionally outside this challenge demo scope.

### Weekly shared-workspace reset

The `Weekly shared demo reset` GitHub Actions workflow calls the protected
`POST /api/v1/admin/reset` endpoint every Monday. Configure the repository
variable `FINZ_DEMO_BASE_URL` with the Render HTTPS origin and the GitHub
Actions secret `FINZ_DEMO_RESET_SECRET` with the same dedicated value stored in
Render. The endpoint clears only the repository-defined shared demo/workflow
collections. It deliberately preserves the encrypted singleton
`qbo_connections` configuration and uses the existing execution lease to
prevent overlap with another protected operation.

## Tests

GitHub Actions runs this same Python 3.12 and pnpm baseline for pull requests
and pushes to `main`.

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest -q

Set-Location ..\frontend
pnpm exec vitest run
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
