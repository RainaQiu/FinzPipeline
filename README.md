# Finz Ledger Bridge

Finz Ledger Bridge imports bank CSV/XLSX data into an immutable internal
ledger, detects duplicates and transfers, applies deterministic accounting
rules, routes uncertain items to review, calculates cash-basis P&L, and prepares
idempotent QuickBooks Online (QBO) outbox items. QBO transaction execution is
intentionally disabled.

## Submission links

- **Public demo:** https://finz-public-demo.onrender.com
- **Source repository:** https://github.com/RainaQiu/FinzPipeline
- **Delivery index:** [SUBMISSION.md](SUBMISSION.md)
- **Submission PDF:**
  [deliverables/Finz_Ledger_Bridge_Submission.pdf](deliverables/Finz_Ledger_Bridge_Submission.pdf)
- **AI usage note:** [docs/ai-usage.md](docs/ai-usage.md)
- **Video:** https://drive.google.com/file/d/1TybjcDxHKtXHPxeipfdgBqSKl1iQqqBO/view?usp=drive_link

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

The deadline deployment in the checked-in `render.yaml` is intentionally a
zero-secret demonstration profile. It uses an ephemeral in-memory repository,
deterministic classification, and QBO Demo/local mode. It demonstrates the
upload, normalization, duplicate/transfer detection, review, and internal P&L
workflow without exposing credentials. QBO writes remain disabled.

To enable the full cloud integration after the deadline demonstration, change
the runtime to the production Mongo profile and set these values manually in
the Render dashboard (they must never be stored in the blueprint):

- `APP_BASE_URL` to the service's HTTPS URL.
- `MONGODB_URI` and `MONGODB_DATABASE` for a non-placeholder Mongo database.
- Sandbox-only `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, and `QBO_REDIRECT_URI`
  (the redirect is `<APP_BASE_URL>/api/v1/integrations/qbo/callback`).
- `QBO_TOKEN_ENCRYPTION_KEY` (a Fernet key), `QBO_EXPECTED_REALM_ID`, and
  `FINZ_DEMO_ACCESS_CODE`. Keep `QBO_SANDBOX_WRITES_ENABLED=false` until a
  reviewed write batch has separate explicit authorization.
- `GEMINI_API_KEY` with `GEMINI_ENABLED=true` to enable the optional runtime
  candidate classifier. Missing/quota-limited Gemini always falls back to
  deterministic rules and human review.
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
when idle and its first request after sleeping may be slow. Data in the current
in-memory deployment is lost whenever the service restarts or sleeps.

The production profile refuses to start with the in-memory repository,
placeholder Mongo settings, non-sandbox QBO, missing QBO settings, a non-HTTPS
public URL, or a missing frontend build. `/health` is liveness; `/ready`
reports dependency readiness without exposing connection details. This is a
shared demonstration environment: do not upload sensitive or real financial
data. Authentication, tenant isolation, and per-user data separation are
intentionally outside this challenge demo scope.

### Minimum cloud setup

1. In MongoDB Atlas, create/select a free transaction-capable cluster, a
   dedicated least-privilege app user, and network access for Render. Put its
   application URI only in Render `MONGODB_URI`.
2. In Render, switch `APP_ENVIRONMENT` to `production`,
   `FINZ_REPOSITORY_BACKEND` to `mongo`, add the secret variables listed
   above, and redeploy. The free service can sleep, so the first request may
   be slow.
3. In Intuit Development settings, add exactly
   `<APP_BASE_URL>/api/v1/integrations/qbo/callback`; keep the app in
   Development/Sandbox and connect only BrightFix Home Services LLC.
4. Generate the Fernet token-encryption key and strong interviewer access
   code locally; store them only in Render secrets. Send only the access code
   to interviewers.
5. Verify `/health`, then `/ready`, connect QBO, run the 21-account preflight,
   and read the Cash-basis P&L. A valid `NoReportData=true` response means
   nothing has been synced yet, not that parsing failed.

Public deployment does not authorize transaction writes. The server requires
all of: `QBO_SANDBOX_WRITES_ENABLED=true`, a one-time 15-minute grant obtained
from the access code, the exact confirmation text shown in the UI, a complete
21-account preflight (`6060 Utilities` must reuse QBO Id `114`), and the
idempotent outbox item. The first real Sandbox write still requires a new,
explicit approval describing entity types, count, period, totals, and rollback.

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

## Technical architecture

The application uses a ports-and-adapters architecture around a deterministic
accounting core:

1. React provides upload, mapping, review, P&L, QBO, and reconciliation views.
2. FastAPI exposes the workflow and integration endpoints.
3. Domain services normalize money and dates, detect duplicates and transfers,
   classify transactions, calculate P&L, and reconcile reports.
4. Repository interfaces isolate persistence from business logic. Both
   in-memory and MongoDB implementations are included.
5. Gemini and QBO are external adapters behind typed interfaces, with mock
   transports for automated tests.
6. The React production build is served by FastAPI so the public deployment
   uses one HTTPS origin.

See [docs/architecture.md](docs/architecture.md) for the concise component
flow.

## Data model

- `RawRecord` preserves immutable source values, file hash, row hash, and
  lineage.
- `NormalizedTransaction` stores canonical date, description, currency,
  bank-account number, direction, and integer-cent amount.
- `ClassificationDecision` stores transaction type, counterparty, account,
  confidence, evidence, approval status, and version.
- Transfer-pair and duplicate status are calculated before P&L inclusion.
- `LedgerLine` and `ProfitAndLoss` provide account-level totals with
  transaction drill-down.
- `OutboxItem` stores an immutable QBO intent, idempotency key, payload kind,
  status, retry metadata, QBO entity ID, and sync token.
- `ReconciliationRun` stores internal amount, QBO amount, difference, status,
  and diagnostic candidates for every account.

Amounts use integer cents or exact `Decimal`; domain accounting never uses
binary floating-point money.

## Classification approach

Deterministic rules run first. They identify transfers, duplicate records,
known merchants, inflows, refunds, owner activity, fixed assets, COGS, and
operating expenses. Each result includes confidence and evidence.

Gemini is an optional candidate classifier only for otherwise-unknown
outflows. It receives minimal normalized fields, must return a strict typed
schema, and can select only from the fixed 21-account chart. Invalid,
low-confidence, unavailable, or quota-limited AI results fall back to manual
review. Gemini cannot approve records, change amounts, calculate P&L, or call
QBO. Human-approved decisions are authoritative.

## QuickBooks integration

The QBO adapter is restricted to the Intuit Development Sandbox and the
expected BrightFix Home Services LLC realm. OAuth state is one-time and
expiring; access and refresh tokens are encrypted before repository storage.
The account preflight requires all 21 numbered accounts and explicitly reuses
existing QBO account ID `114` for `6060 Utilities`.

Approved transactions become outbox items before any network write. A Sandbox
write additionally requires a server-side enable flag, a one-time access
grant, exact confirmation text, an item preview, account preflight, and an
execution lease. The QBO entity ID and sync token are retained after success.
The report adapter requests Cash-basis Profit and Loss data for an exact period
and supports QBO's valid `NoReportData=true` empty-report shape.

The current public deadline deployment does not contain QBO credentials and
does not execute QBO writes.

## Duplicate prevention

Source rows retain stable hashes, and normalized transactions receive
deterministic fingerprints derived from canonical business fields. Duplicate
detection runs before classification and excludes duplicate extras from P&L
and sync candidates. Overlapping uploads are checked through repository
indexes rather than silently creating another economic transaction.

QBO posting uses a separate idempotency key based on Sandbox realm,
transaction identity, and classification version. The outbox repository
enforces uniqueness, and the gateway sends a stable QBO request ID so retries
do not create another transaction.

## Assumptions

- The challenge workbook is synthetic, denominated in USD, and covers
  2026-04-01 through 2026-06-30.
- Account numbers in the supplied 21-account chart are authoritative.
- Bank-account inflows are positive and outflows are negative after
  normalization.
- Cash-basis P&L excludes transfers, owner activity, duplicates, and
  fixed-asset purchases.
- Low-confidence and exceptional records require human approval.
- Only BrightFix Home Services LLC in a QBO Development Sandbox is in scope;
  Production QBO and real customer data are prohibited.

## Known limitations

- The public deadline deployment uses an in-memory repository; data disappears
  when the free Render instance restarts or sleeps.
- MongoDB Atlas, live Gemini classification, and live QBO OAuth are not enabled
  in the public deployment because secrets are intentionally absent.
- No real QBO Sandbox transaction write has been executed or claimed.
- The verified QBO Cash P&L response is currently an empty
  `NoReportData=true` report because no challenge transactions were posted.
- The public demo is a shared workspace without login, tenant isolation, RBAC,
  or per-user data separation. It must not receive sensitive data.
- The free Render service can sleep and may take approximately 50 seconds to
  respond to the first request.
- Production enablement still requires Atlas configuration, secret injection,
  an Intuit redirect URI, BrightFix OAuth consent, and explicit authorization
  before the first Sandbox write.

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
- QBO sync endpoints create idempotent outbox items. Real Sandbox execution
  remains disabled by default and requires account preflight, an access grant,
  exact confirmation, a reviewed item preview, and explicit user authorization
  for the first real write.
- MongoDB Atlas and live QBO writes are not part of the verified local baseline.

Design and implementation documents live under `docs/superpowers/`.
