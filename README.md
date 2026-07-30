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
- `FINZ_DEMO_ACCESS_CODE` to a strong interviewer access code of at least 12
  characters. Keep it separate from the reset secret and send it outside the
  public repository.
- `GEMINI_API_KEY` to the dedicated runtime key. `GEMINI_ENABLED=true`,
  `GEMINI_MODEL=gemini-3.5-flash-lite`, and the per-upload candidate cap are
  already declared by the blueprint. If the key is absent, Gemini is disabled
  and deterministic classification continues normally.

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

### Runtime Gemini boundary

Codex was used as a development tool. Gemini is the optional runtime
candidate classifier required by the challenge: deterministic rules run
first, and Gemini is consulted only for otherwise-unknown outflows, up to ten
times per upload. It receives normalized minimal fields rather than the
uploaded file and can return only a typed candidate from the fixed 21-account
chart. Every Gemini result remains a suggested item requiring human review;
rules, schema/accounting validation, and human approval are authoritative.

The automated Gemini coverage is mock/contract verification and does not
prove a live Google API call. A future live smoke test must use only minimal
fields from the challenge's synthetic data, never a raw file or sensitive
financial data. See [docs/ai-usage.md](docs/ai-usage.md).

### Weekly shared-workspace reset

The `Weekly shared demo reset` GitHub Actions workflow calls the protected
`POST /api/v1/admin/reset` endpoint every Monday. Configure the repository
variable `FINZ_DEMO_BASE_URL` with the Render HTTPS origin and the GitHub
Actions secret `FINZ_DEMO_RESET_SECRET` with the same dedicated value stored in
Render. The endpoint clears only the repository-defined shared demo/workflow
collections. It deliberately preserves the encrypted singleton
`qbo_connections` configuration and uses the existing execution lease to
prevent overlap with another protected operation.

The public deployment requires a transaction-capable MongoDB topology (Atlas,
a replica set, or mongos) because each lease renewal and collection clear is
committed atomically. The local standalone Docker MongoDB remains valid for
ordinary repository development, but the reset endpoint reports unavailable
there and Atlas-only reset transaction tests are explicitly skipped.

### Interviewer access grants

`POST /api/v1/demo/access-grants` exchanges the configured interviewer access
code for a random bearer grant that expires after 15 minutes. The response is
marked `no-store` and returns the bearer only once; the repository stores only
its SHA-256 hash. A protected operation atomically consumes the grant, so it
cannot be reused. Invalid codes receive a fixed short delay and a generic
error. This is deliberately a narrow gate for the shared challenge demo, not
user authentication or tenant isolation.

The endpoint does not connect to or write QBO. The later guarded Sandbox sync
step will require both a one-time grant and a separate explicit confirmation;
the first real QBO Sandbox transaction remains subject to explicit user
authorization.

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
