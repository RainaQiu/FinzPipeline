# Finz Public Cloud Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish Finz Ledger Bridge as a free, publicly accessible, anonymous shared demo that persists data in MongoDB Atlas, performs access-code-gated writes to the dedicated BrightFix QuickBooks Online Sandbox, pulls the QBO cash-basis P&L through the API, reconciles to exactly $0.00, and resets demo data weekly.

**Architecture:** GitHub Pages serves the React application, a Render Free Web Service runs the FastAPI API, and a MongoDB Atlas Free cluster stores the shared workspace. The browser never receives QBO, Gemini, MongoDB, cleanup, encryption, or access-code secrets. Real QBO Sandbox execution remains behind validation, an opaque 15-minute demo grant, an explicit confirmation, an outbox, idempotency keys, retries, audit events, and a single-run lease.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, httpx, MongoDB/PyMongo async API, cryptography/Fernet, React 19, TypeScript, Vite, Vitest, GitHub Pages, GitHub Actions, Render Free, MongoDB Atlas Free, Gemini API, Intuit OAuth 2.0 and QBO v3 API.

## Global Constraints

- `D:\MISM\Finz` is the only project root.
- The cloud environment is a deliberately shared, anonymous demo workspace; authentication, tenant authorization, and per-user isolation are explicitly out of scope and documented as production extensions.
- Display this message before upload and in the persistent shell: “Public demo environment. Do not upload sensitive or confidential data. All visitors share one workspace and may view or modify its contents. Authentication, authorization, and tenant isolation are intentionally excluded from this evaluation build, not overlooked in the production architecture.”
- Clear shared application data and only verified Finz-created QBO Sandbox transactions every Sunday at `03:17 UTC`.
- QBO environment must equal `sandbox`; startup must fail closed if cloud execution is enabled with any other value.
- Never accept a QBO realm ID from a public request. Use the one encrypted, server-side connection for `BrightFix Home Services LLC`.
- Never expose or log QBO tokens, Client ID, Client Secret, MongoDB URI, Gemini credentials, cleanup token, encryption key, access code, or demo grant.
- Real QBO writes require a valid 15-minute opaque demo grant and a second explicit `confirm=true` request field.
- QBO entities must use resolved QBO internal account IDs, not chart-of-accounts numbers.
- Only approved transactions, the 21-account whitelist, the challenge date range `2026-04-01` through `2026-06-30`, USD, configured bank accounts `1000` and `1010`, integer cents, and balanced transfer pairs may reach the QBO gateway.
- QBO writes use outbox claims, idempotency keys, retry classification, audit events, and a single active execution lease.
- A weekly cleanup may delete only QBO entities whose entity ID, sync token, kind, idempotency key, and `FinzDemo:` marker are all present in this application’s succeeded outbox records.
- Gemini may generate only a typed candidate account/type/explanation. Existing deterministic validation, confidence thresholds, the account whitelist, amount invariants, and manual review remain authoritative.
- GitHub Pages and Render deploy from `main`; pull requests run tests without using live QBO, Gemini, Atlas, or cleanup secrets.
- Every external dependency must retain a protocol and fake. Unit/contract tests must not make live network calls.
- Do not modify or print the local `.env`; update `.env.example` with names and non-secret placeholders only.
- Do not execute a real QBO Sandbox write until the user separately approves the execution checkpoint after mock, contract, Atlas, and cloud read-only tests pass.

---

## File Map

### Backend domain and persistence

- Create `backend/app/domain/demo.py`: upload, pipeline context, sync-run, reconciliation-run, access-grant, QBO-connection, execution-lease, and reset-run records.
- Modify `backend/app/repositories/protocols.py`: repository contracts for those records and safe demo reset.
- Modify `backend/app/repositories/memory.py`: deterministic test implementations.
- Modify `backend/app/repositories/mongo.py`: Atlas implementations, TTL/unique indexes, atomic grants and leases.
- Modify `backend/app/services/ledger_bridge.py`: replace all process-memory dictionaries with repositories.

### External integrations and controls

- Create `backend/app/services/demo_access.py`: high-entropy access-code verification and opaque short-lived grants.
- Create `backend/app/integrations/quickbooks/gateway.py`: encrypted connection loading, refresh, account resolution, entity create/delete, and report retrieval.
- Modify `backend/app/integrations/quickbooks/protocol.py`: read, write, delete, and report contracts.
- Modify `backend/app/integrations/quickbooks/client.py`: OAuth token persistence and refresh-safe response handling.
- Modify `backend/app/services/qbo_sync.py`: valid QBO payloads, Finz marker, account-ID resolution, execution lease, and retry flow.
- Create `backend/app/services/demo_reset.py`: weekly shared-workspace and QBO cleanup orchestration.
- Create `backend/app/integrations/gemini/client.py`: structured Gemini candidates through the existing AI port.

### API and frontend

- Create `backend/app/api/demo.py`: disclosure metadata, grant creation, reset status, and protected cleanup endpoint.
- Modify `backend/app/api/qbo_oauth.py`: owner-only bootstrap and encrypted persistent connection.
- Modify `backend/app/api/qbo_sync.py`: plan, authorize, execute, status, and retry APIs.
- Modify `backend/app/api/reconciliations.py`: fetch QBO P&L server-side instead of accepting a browser-supplied report.
- Modify `backend/app/core/config.py` and `backend/app/main.py`: production settings, CORS, startup checks, and dependency wiring.
- Create `frontend/src/components/DemoDisclosure.tsx`: unavoidable shared-demo warning.
- Create `frontend/src/features/qbo/QboAccessDialog.tsx`: access-code exchange and explicit execution confirmation.
- Modify `frontend/src/features/qbo/QboPage.tsx`, `frontend/src/features/reconciliation/ReconciliationPage.tsx`, `frontend/src/api/client.ts`, `frontend/src/types.ts`, `frontend/src/main.tsx`, and `frontend/src/styles.css`.

### Deployment and operations

- Create `backend/Dockerfile`, `render.yaml`, `.github/workflows/ci.yml`, `.github/workflows/deploy-pages.yml`, and `.github/workflows/weekly-demo-reset.yml`.
- Modify `frontend/vite.config.ts`, `.env.example`, `README.md`, `docs/architecture.md`, `docs/demo-script.md`, and `docs/ai-usage.md`.
- Create `docs/cloud-deployment.md` and `docs/cloud-demo-runbook.md`.

---

### Task 1: Freeze the New Baseline and Add Cloud CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Test: existing backend and frontend suites

**Interfaces:**
- Consumes: the merged `main` branch.
- Produces: a reproducible Python 3.12 and pnpm CI baseline that later tasks must keep green.

- [ ] **Step 1: Preserve the workbook change before changing branches**

Run:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item -LiteralPath 'Finz Accounting Data Engineering Challenge Dataset.xlsx' `
  -Destination "tmp\dataset-backups\Finz-dataset-$stamp.xlsx"
Get-FileHash 'Finz Accounting Data Engineering Challenge Dataset.xlsx'
Get-FileHash "tmp\dataset-backups\Finz-dataset-$stamp.xlsx"
```

Expected: the two SHA-256 values match; do not stage either workbook.

- [ ] **Step 2: Update the local baseline without discarding the workbook**

Run:

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c agent/public-cloud-demo
git status --short
```

Expected: the new branch starts from the merged `main`, and the workbook remains the only unrelated local modification.

- [ ] **Step 3: Run the pre-cloud baseline**

Run:

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest -q
Set-Location ..\frontend
pnpm test -- --run
pnpm build
```

Expected: all backend tests, 14 or more frontend tests, and the production build pass.

- [ ] **Step 4: Add CI**

Create `.github/workflows/ci.yml` with two jobs:

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r backend/requirements.txt
      - run: pytest -q
        working-directory: backend
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 11.9.0
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
        working-directory: frontend
      - run: pnpm test -- --run
        working-directory: frontend
      - run: pnpm build
        working-directory: frontend
```

- [ ] **Step 5: Commit**

```powershell
git add -- .github/workflows/ci.yml README.md
git commit -m "Add cloud deployment CI baseline"
```

---

### Task 2: Define Persistent Cloud Orchestration Records

**Files:**
- Create: `backend/app/domain/demo.py`
- Modify: `backend/app/repositories/protocols.py`
- Test: `backend/tests/unit/test_demo_domain.py`

**Interfaces:**
- Produces:
  - `UploadRecord`
  - `PipelineContext`
  - `SyncRunRecord`
  - `ReconciliationRunRecord`
  - `DemoGrant`
  - `QboConnection`
  - `ExecutionLease`
  - `ResetRun`
  - `UploadRepository`, `PipelineContextRepository`, `SyncRunRepository`, `ReconciliationRunRepository`, `DemoGrantRepository`, `QboConnectionRepository`, `ExecutionLeaseRepository`, and `DemoResetRepository`.

- [ ] **Step 1: Write failing immutable-domain tests**

Test exact invariants:

```python
def test_demo_grant_never_retains_plaintext_token():
    grant = DemoGrant(
        token_hash="a" * 64,
        expires_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert not hasattr(grant, "token")


def test_qbo_connection_repr_redacts_ciphertext():
    connection = QboConnection(
        realm_id="realm-1",
        company_name="BrightFix Home Services LLC",
        encrypted_access_token="cipher-a",
        encrypted_refresh_token="cipher-r",
        access_expires_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        refresh_expires_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert "cipher-a" not in repr(connection)
    assert "cipher-r" not in repr(connection)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_demo_domain.py -q
```

Expected: import failure for `app.domain.demo`.

- [ ] **Step 3: Implement focused records**

Use frozen, slotted dataclasses. `UploadRecord.data` is immutable `bytes`; QBO ciphertext fields use `field(repr=False)`; every timestamp must be timezone-aware. `PipelineContext` contains duplicate status and transfer-pair data required to reconstruct sync candidates after a restart. Run and reconciliation records store immutable view mappings rather than process dictionaries.

- [ ] **Step 4: Add repository protocols**

Add exact methods:

```python
class DemoGrantRepository(Protocol):
    async def issue(self, grant: DemoGrant) -> DemoGrant: ...
    async def consume_valid(self, token_hash: str, *, now: datetime) -> DemoGrant | None: ...


class ExecutionLeaseRepository(Protocol):
    async def acquire(self, lease: ExecutionLease, *, now: datetime) -> bool: ...
    async def release(self, lease_id: str) -> None: ...


class QboConnectionRepository(Protocol):
    async def upsert(self, connection: QboConnection) -> QboConnection: ...
    async def get(self) -> QboConnection | None: ...
```

Extend `UnitOfWork` with all new repositories.

- [ ] **Step 5: Run tests and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_demo_domain.py tests/unit/test_domain_models.py -q
git add -- backend/app/domain/demo.py backend/app/repositories/protocols.py backend/tests/unit/test_demo_domain.py
git commit -m "Define persistent cloud demo records"
```

---

### Task 3: Implement In-Memory and MongoDB Cloud Repositories

**Files:**
- Modify: `backend/app/repositories/memory.py`
- Modify: `backend/app/repositories/mongo.py`
- Test: `backend/tests/unit/test_memory_repositories.py`
- Test: `backend/tests/integration/test_mongo_cloud_repositories.py`

**Interfaces:**
- Consumes: Task 2 protocols.
- Produces: atomic grant consumption, execution leases, persisted orchestration state, and scoped reset support for both repository engines.

- [ ] **Step 1: Write failing in-memory tests**

Cover:

```python
async def test_demo_grant_is_single_use_and_expires(): ...
async def test_only_one_execution_lease_can_be_active(): ...
async def test_reset_clears_demo_records_but_keeps_configuration(): ...
async def test_upload_bytes_round_trip_without_mutation(): ...
```

- [ ] **Step 2: Run in-memory tests and verify RED**

Run:

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_memory_repositories.py -q
```

Expected: missing repository attributes on `InMemoryUnitOfWork`.

- [ ] **Step 3: Implement in-memory repositories**

Reuse the unit of work’s `asyncio.Lock` pattern. `consume_valid` must delete the matching grant atomically. `acquire` must reject an unexpired existing lease and replace an expired lease. Reset must not remove account configuration or the current QBO connection.

- [ ] **Step 4: Write Mongo integration tests**

Use only `finz_ledger_bridge_test` and unique test IDs prefixed `finz-test-`. Assert:

- TTL indexes on `demo_grants.expires_at`, `execution_leases.expires_at`, and `oauth_states.expires_at`.
- unique indexes on `uploads.id`, `sync_runs.id`, `reconciliation_runs.id`, `qbo_connections.singleton`, and `outbox.idempotency_key`.
- two concurrent lease acquisitions yield exactly one `True`.
- a second grant consumption returns `None`.
- scoped reset leaves `qbo_connections` intact.

- [ ] **Step 5: Implement Mongo repositories and indexes**

Use `find_one_and_delete` for grants and `find_one_and_update` with expiry conditions for leases. Add repository collections to `index_information()`. Do not use a collection-wide delete outside `MongoDemoResetRepository.clear_shared_workspace()`.

- [ ] **Step 6: Verify real local MongoDB**

Run:

```powershell
& ..\.venv312\Scripts\python.exe ..\scripts\run_mongo_integration.py
```

Expected: the new repository tests run against the real local MongoDB container and pass. If Docker is unavailable, record the exact failure and keep mock/unit verification distinct.

- [ ] **Step 7: Commit**

```powershell
git add -- backend/app/repositories/memory.py backend/app/repositories/mongo.py backend/tests/unit/test_memory_repositories.py backend/tests/integration/test_mongo_cloud_repositories.py
git commit -m "Persist cloud demo orchestration state"
```

---

### Task 4: Remove Process-Memory State from LedgerBridgeService

**Files:**
- Modify: `backend/app/services/ledger_bridge.py`
- Test: `backend/tests/integration/test_service_restart_persistence.py`
- Test: `backend/tests/integration/test_api_workflow.py`

**Interfaces:**
- Consumes: Task 3 repositories.
- Produces: upload, processing, sync-run, transfer context, and reconciliation behavior that survives service reconstruction.

- [ ] **Step 1: Write a failing restart test**

The test must:

1. create and process an upload through `LedgerBridgeService(uow)`;
2. discard that service instance;
3. construct a new `LedgerBridgeService(uow)`;
4. retrieve the upload, plan a transfer-aware sync, and retrieve the sync run;
5. assert all views match.

- [ ] **Step 2: Verify RED**

Run:

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/integration/test_service_restart_persistence.py -q
```

Expected: “Upload not found” or missing sync run after reconstruction.

- [ ] **Step 3: Replace dictionaries with repositories**

Remove `_uploads`, `_duplicate_status`, `_transfer_pair_by_transaction`, `_transfer_sync_context`, `_sync_runs`, and `_reconciliation_runs`. Keep only dependency references. Persist upload bytes before returning the upload ID; persist pipeline context in the same processing operation; store sync and reconciliation run views before returning.

- [ ] **Step 4: Verify restart and existing workflows**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/integration/test_service_restart_persistence.py tests/integration/test_api_workflow.py tests/integration/test_golden_ingestion.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add -- backend/app/services/ledger_bridge.py backend/tests/integration/test_service_restart_persistence.py backend/tests/integration/test_api_workflow.py
git commit -m "Make ledger workflows restart safe"
```

---

### Task 5: Add Public Demo Disclosure and Production API Configuration

**Files:**
- Create: `frontend/src/components/DemoDisclosure.tsx`
- Create: `frontend/src/components/DemoDisclosure.test.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/features/upload/UploadPage.tsx`
- Modify: `frontend/src/features/upload/UploadPage.test.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Produces:
  - persistent disclosure banner;
  - pre-upload acknowledgement checkbox;
  - `VITE_API_BASE_URL` support;
  - GitHub Pages-safe routing and asset base.

- [ ] **Step 1: Write failing disclosure tests**

Assert the exact concepts “shared workspace,” “do not upload sensitive,” and “intentionally excluded, not overlooked” appear. Assert `Upload and preview` remains disabled until both a file and acknowledgement are present.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location frontend
pnpm exec vitest run src/components/DemoDisclosure.test.tsx src/features/upload/UploadPage.test.tsx
```

- [ ] **Step 3: Implement the disclosure**

Render `DemoDisclosure` at the top of `AppShell` and a shorter acknowledgement beside the upload action. Change the sidebar footer from “Local review workspace” to “Public shared demo · weekly reset.”

- [ ] **Step 4: Add an explicit API base**

Use:

```ts
const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const apiUrl = (path: string) => `${apiBase}${path}`;
```

All `fetch` calls must use `apiUrl(path)`. Local development keeps an empty base and the Vite proxy.

- [ ] **Step 5: Make GitHub Pages routing deterministic**

Use `HashRouter` in `frontend/src/main.tsx`. In `vite.config.ts`, set:

```ts
base: process.env.GITHUB_ACTIONS ? "/FinzPipeline/" : "/",
```

- [ ] **Step 6: Fix the remaining narrow-screen quality-note spacing**

Add a grid gap to `.quality-note` and assert the rendered text includes a boundary between “transactions out” and “5 exact duplicates.”

- [ ] **Step 7: Verify and commit**

```powershell
pnpm test -- --run
pnpm build
git add -- frontend/src/components frontend/src/features/upload frontend/src/api/client.ts frontend/src/main.tsx frontend/src/styles.css frontend/vite.config.ts
git commit -m "Add public demo disclosure and cloud API routing"
```

---

### Task 6: Add Production Settings, CORS, and Fail-Closed Startup

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`
- Modify: `.env.example`
- Test: `backend/tests/unit/test_config.py`
- Test: `backend/tests/integration/test_cors.py`

**Interfaces:**
- Produces settings for `APP_ENV`, `FRONTEND_ORIGINS`, `FINZ_PUBLIC_DEMO`, `FINZ_QBO_EXECUTION_ENABLED`, `FINZ_DEMO_SYNC_CODE_HASH`, `FINZ_DEMO_TOKEN_PEPPER`, `FINZ_QBO_TOKEN_ENCRYPTION_KEY`, `FINZ_QBO_ADMIN_CODE_HASH`, `FINZ_CLEANUP_TOKEN_HASH`, `GEMINI_API_KEY`, and `GEMINI_MODEL`.

- [ ] **Step 1: Write failing configuration tests**

Assert:

- cloud mode requires MongoDB;
- QBO execution requires `QBO_ENVIRONMENT=sandbox`;
- QBO execution requires all QBO credentials, encryption key, and access-code hash;
- secret fields are `SecretStr` and absent from `repr(settings)`;
- `FRONTEND_ORIGINS` parses exact HTTPS origins and rejects `*`;
- defaults keep local tests in memory with QBO writes off.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_config.py tests/integration/test_cors.py -q
```

- [ ] **Step 3: Extend Settings**

Do not load `.env` implicitly. Parse comma-separated origins into a tuple. Store all secret values as `SecretStr`. Add `cryptography` to `backend/requirements.txt` for Fernet token encryption.

- [ ] **Step 4: Add exact CORS policy**

Install `CORSMiddleware` only with configured origins, methods `GET`, `POST`, and `PATCH`, and headers `Content-Type` and `X-Finz-Demo-Grant`. Do not enable wildcard credentials.

- [ ] **Step 5: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pip install -r requirements.txt
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_config.py tests/integration/test_cors.py -q
git add -- backend/app/core/config.py backend/app/main.py backend/requirements.txt backend/tests/unit/test_config.py backend/tests/integration/test_cors.py .env.example
git commit -m "Add fail-closed cloud configuration"
```

---

### Task 7: Implement Access-Code Grants

**Files:**
- Create: `backend/app/services/demo_access.py`
- Create: `backend/app/api/demo.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_demo_access.py`
- Test: `backend/tests/integration/test_demo_access_api.py`

**Interfaces:**
- Produces:
  - `hash_access_code(code: str, salt: bytes) -> str`
  - `DemoAccessService.issue_grant(code: str, now: datetime) -> tuple[str, datetime]`
  - `DemoAccessService.consume_grant(token: str, now: datetime) -> bool`
  - `POST /api/v1/demo/grants`
  - `GET /api/v1/demo/status`

- [ ] **Step 1: Write failing service tests**

Use stdlib `hashlib.scrypt`. Assert correct code issues a 256-bit URL-safe opaque token, wrong code returns the same public error, only the token hash is stored, grants expire after 15 minutes, and a grant can authorize exactly one execution request.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_demo_access.py tests/integration/test_demo_access_api.py -q
```

- [ ] **Step 3: Implement the service and API**

`POST /api/v1/demo/grants` accepts:

```json
{"access_code":"user-entered-value"}
```

Return:

```json
{"grant_token":"opaque-random-value","expires_at":"2026-07-29T16:15:00Z"}
```

Apply a fixed delay floor and per-IP in-memory rate limit of five failed attempts per 15 minutes; Render remains one instance. Never echo the submitted code.

- [ ] **Step 4: Add secure logging tests**

Send sentinel access codes and grants, then assert neither appears in captured `uvicorn.access` nor application logs.

- [ ] **Step 5: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_demo_access.py tests/integration/test_demo_access_api.py tests/unit/test_secure_logging.py -q
git add -- backend/app/services/demo_access.py backend/app/api/demo.py backend/app/main.py backend/tests/unit/test_demo_access.py backend/tests/integration/test_demo_access_api.py backend/tests/unit/test_secure_logging.py
git commit -m "Gate demo sync with short-lived grants"
```

---

### Task 8: Persist, Encrypt, and Refresh the QBO Sandbox Connection

**Files:**
- Modify: `backend/app/integrations/quickbooks/client.py`
- Modify: `backend/app/api/qbo_oauth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_qbo_oauth_persistence.py`
- Test: `backend/tests/integration/test_qbo_oauth_api.py`

**Interfaces:**
- Consumes: `QboConnectionRepository`.
- Produces:
  - encrypted tokens at rest;
  - `QuickBooksClient.get_valid_access_token() -> tuple[str, str]`;
  - owner-only initial OAuth bootstrap through `POST /api/v1/integrations/qbo/admin/connect`;
  - public read-only connection status.

- [ ] **Step 1: Write failing token-persistence tests**

Use `httpx.MockTransport`. Assert:

- authorization stores ciphertext, realm, BrightFix company name, and expiries;
- plaintext tokens never appear in the Mongo document or object `repr`;
- a valid token is reused;
- an expired token triggers exactly one refresh;
- the latest refresh token replaces the prior one;
- concurrent refresh callers share one lock;
- a 401 performs one refresh-and-retry, then returns a sanitized error.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_qbo_oauth_persistence.py tests/integration/test_qbo_oauth_api.py -q
```

- [ ] **Step 3: Implement the owner-only OAuth start**

`POST /api/v1/integrations/qbo/admin/connect` requires `X-Finz-Qbo-Admin-Code`, verifies it against `FINZ_QBO_ADMIN_CODE_HASH`, stores a one-time OAuth state, and returns an Intuit authorization URL. The public GET `/connect` route is removed. The admin code never appears in a URL.

- [ ] **Step 4: Implement encrypted callback persistence and refresh**

The callback consumes the persisted one-time state, exchanges the authorization code, verifies `BrightFix Home Services LLC`, encrypts and persists the newest access and refresh tokens, then redirects to the GitHub Pages QBO route without OAuth parameters. Decrypt only inside the HTTP integration boundary. When a valid connection exists, the admin start endpoint returns `409` unless the request includes `replace=true` and a fresh valid admin code. This owner code is never sent to interviewers.

- [ ] **Step 5: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_qbo_oauth_persistence.py tests/integration/test_qbo_oauth_api.py tests/test_app.py -q
git add -- backend/app/integrations/quickbooks/client.py backend/app/api/qbo_oauth.py backend/app/main.py backend/tests/unit/test_qbo_oauth_persistence.py backend/tests/integration/test_qbo_oauth_api.py
git commit -m "Persist encrypted QBO sandbox tokens"
```

---

### Task 9: Implement the Real QBO Gateway and Account Resolver

**Files:**
- Modify: `backend/app/integrations/quickbooks/protocol.py`
- Create: `backend/app/integrations/quickbooks/gateway.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/fakes/fake_qbo.py`
- Test: `backend/tests/contract/test_qbo_gateway.py`
- Test: `backend/tests/contract/test_qbo_payloads.py`

**Interfaces:**
- Produces:

```python
class QuickBooksGateway(Protocol):
    async def resolve_accounts(self, numbers: tuple[str, ...]) -> Mapping[str, str]: ...
    async def create_entity(self, kind: str, payload: Mapping[str, object]) -> QboCreateResult: ...
    async def fetch_profit_and_loss(self, start_date: date, end_date: date) -> Mapping[str, object]: ...
    async def delete_entity(self, kind: str, entity_id: str, sync_token: str) -> None: ...
```

- [ ] **Step 1: Write failing contract tests**

Mock QBO responses and assert:

- account query maps all 21 `AcctNum` values to internal QBO `Id` values;
- missing or duplicate account numbers fail before any transaction write;
- create paths are `/company/{realm}/deposit`, `/purchase`, and `/transfer`;
- report path is `/company/{realm}/reports/ProfitAndLoss` with `accounting_method=Cash`, `start_date`, and `end_date`;
- delete requires ID and sync token and rejects entities absent from the Finz outbox.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/contract/test_qbo_gateway.py tests/contract/test_qbo_payloads.py -q
```

- [ ] **Step 3: Implement the gateway**

Use the persistent client from Task 8, `minorversion=75`, 20-second timeouts, one refresh retry on 401, `Retry-After` handling for 429, and sanitized exceptions. Account resolution must complete before planning executable payloads.

- [ ] **Step 4: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/contract/test_qbo_gateway.py tests/contract/test_qbo_payloads.py tests/unit/test_secure_logging.py -q
git add -- backend/app/integrations/quickbooks backend/app/main.py backend/tests/fakes/fake_qbo.py backend/tests/contract
git commit -m "Add real QBO sandbox gateway"
```

---

### Task 10: Correct QBO Payload Accounting and Execute the Outbox

**Files:**
- Modify: `backend/app/services/qbo_sync.py`
- Modify: `backend/app/services/ledger_bridge.py`
- Modify: `backend/app/api/qbo_sync.py`
- Test: `backend/tests/unit/test_qbo_sync.py`
- Test: `backend/tests/integration/test_qbo_execution_api.py`

**Interfaces:**
- Consumes: Tasks 7–9.
- Produces:
  - `POST /api/v1/integrations/qbo/sync/plan`
  - `POST /api/v1/integrations/qbo/sync-runs/{run_id}/execute`
  - `POST /api/v1/integrations/qbo/sync-items/{item_id}/retry`
  - `GET /api/v1/integrations/qbo/status`

- [ ] **Step 1: Write failing accounting payload tests**

Assert:

- revenue and owner contributions create positive Deposits;
- refunds create positive Purchases from bank account to account `4100`, not negative Deposits;
- COGS, operating expenses, fixed assets, and owner distributions create positive Purchases;
- transfers use one equal-and-opposite pair;
- every payload contains `PrivateNote: "FinzDemo:<idempotency-key>"`;
- every `AccountRef.value` is a resolved QBO internal ID;
- unsupported currency, dates, accounts, amount mutation, or unapproved decisions fail before gateway calls.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_qbo_sync.py tests/contract/test_qbo_payloads.py -q
```

- [ ] **Step 3: Implement executable planning**

Remove the public realm field. Load the realm from `QboConnectionRepository`. Resolve all account IDs once per plan. Persist both account numbers and resolved IDs in the immutable outbox payload.

- [ ] **Step 4: Write failing execution API tests**

Assert:

- missing grant returns `403`;
- `confirm=false` returns `422`;
- the same grant cannot execute twice;
- one execution lease prevents concurrent runs;
- succeeded items are not posted twice;
- retryable failures retain safe codes and retry dates;
- permanent failures cannot be retried;
- response includes succeeded, retryable-failed, and permanent-failed counts;
- audit events contain IDs and statuses but no payload secrets.

- [ ] **Step 5: Implement execution and retry endpoints**

Execution consumes the grant at the start, acquires a five-minute lease, claims pending items atomically, calls `process_outbox_item(..., allow_writes=True)`, records results, and releases the lease in `finally`.

- [ ] **Step 6: Verify all mock/contract tests**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_qbo_sync.py tests/contract/test_qbo_payloads.py tests/integration/test_qbo_execution_api.py -q
```

Expected: no real QBO network access.

- [ ] **Step 7: Commit**

```powershell
git add -- backend/app/services/qbo_sync.py backend/app/services/ledger_bridge.py backend/app/api/qbo_sync.py backend/tests/unit/test_qbo_sync.py backend/tests/contract/test_qbo_payloads.py backend/tests/integration/test_qbo_execution_api.py
git commit -m "Execute gated idempotent QBO sandbox sync"
```

---

### Task 11: Pull and Reconcile the Real QBO Cash-Basis P&L

**Files:**
- Modify: `backend/app/services/reconciliation.py`
- Modify: `backend/app/services/ledger_bridge.py`
- Modify: `backend/app/api/reconciliations.py`
- Test: `backend/tests/unit/test_reconciliation.py`
- Test: `backend/tests/contract/test_qbo_pnl_report.py`
- Test: `backend/tests/integration/test_qbo_reconciliation_api.py`

**Interfaces:**
- Produces `POST /api/v1/reconciliations` with only `start_date` and `end_date`; the server fetches the connected Sandbox report.

- [ ] **Step 1: Write failing QBO report parser tests**

Use realistic nested QBO report fixtures. Assert:

- `ReportBasis` must be `Cash`;
- report dates must exactly match the requested period;
- account rows map by `account_num`, not display order;
- decimal strings convert to integer cents without float;
- net income parses separately;
- unknown accounts are diagnostics and cannot silently change internal totals.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/contract/test_qbo_pnl_report.py tests/unit/test_reconciliation.py -q
```

- [ ] **Step 3: Replace browser-supplied QBO reports**

Remove `qbo_report` from `ReconciliationRequest`. Fetch through `QuickBooksGateway.fetch_profit_and_loss`, parse, reconcile with zero-cent tolerance, persist the raw snapshot and normalized comparison, and return mismatch diagnostics.

- [ ] **Step 4: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/contract/test_qbo_pnl_report.py tests/unit/test_reconciliation.py tests/integration/test_qbo_reconciliation_api.py -q
git add -- backend/app/services/reconciliation.py backend/app/services/ledger_bridge.py backend/app/api/reconciliations.py backend/tests/contract/test_qbo_pnl_report.py backend/tests/unit/test_reconciliation.py backend/tests/integration/test_qbo_reconciliation_api.py
git commit -m "Reconcile against the QBO cash-basis report"
```

---

### Task 12: Connect Gemini Through the Existing Candidate-Only Port

**Files:**
- Create: `backend/app/integrations/gemini/__init__.py`
- Create: `backend/app/integrations/gemini/client.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/classification.py`
- Modify: `.env.example`
- Modify: `docs/ai-usage.md`
- Test: `backend/tests/contract/test_gemini_client.py`
- Test: `backend/tests/unit/test_ai_validation.py`

**Interfaces:**
- Consumes: the existing AI candidate protocol and validator.
- Produces: `GeminiCandidateProvider.propose(transaction) -> ClassificationCandidate`.

- [ ] **Step 1: Write failing structured-output tests**

With `httpx.MockTransport`, assert the client requests JSON fields `account_number`, `transaction_type`, `explanation`, and `confidence_basis_points`; sends only normalized transaction facts; excludes bank credentials and QBO tokens; rejects markdown, extra fields, unknown accounts, amount fields, and invalid transaction types.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/contract/test_gemini_client.py tests/unit/test_ai_validation.py -q
```

- [ ] **Step 3: Implement the provider**

Call the current Gemini `generateContent` REST API with the secret in `x-goog-api-key`, model from `GEMINI_MODEL`, a 15-second timeout, deterministic temperature, JSON response schema, and sanitized errors. Invoke Gemini only when deterministic rules cannot produce a safe candidate; always pass the result through the existing validator.

- [ ] **Step 4: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/contract/test_gemini_client.py tests/unit/test_ai_validation.py tests/unit/test_classification.py -q
git add -- backend/app/integrations/gemini backend/app/main.py backend/app/services/classification.py backend/tests/contract/test_gemini_client.py backend/tests/unit/test_ai_validation.py .env.example docs/ai-usage.md
git commit -m "Add validated Gemini classification candidates"
```

---

### Task 13: Build the Cloud QBO and Reconciliation UX

**Files:**
- Create: `frontend/src/features/qbo/QboAccessDialog.tsx`
- Create: `frontend/src/features/qbo/QboAccessDialog.test.tsx`
- Modify: `frontend/src/features/qbo/QboPage.tsx`
- Modify: `frontend/src/features/qbo/QboPage.test.tsx`
- Modify: `frontend/src/features/reconciliation/ReconciliationPage.tsx`
- Modify: `frontend/src/features/reconciliation/ReconciliationPage.test.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Tasks 7, 10, and 11 APIs.
- Produces: plan preview, access-code modal, explicit Sandbox confirmation, execution progress/results, retry controls, and server-fetched reconciliation.

- [ ] **Step 1: Write failing QBO UX tests**

Assert:

- status shows `Sandbox connected` and company `BrightFix Home Services LLC`;
- plan can be created without a code;
- execute opens the access dialog;
- the code field uses `type=password` and is cleared after exchange;
- the confirmation names the number of entities and says “Sandbox only”;
- grant stays in React memory only, not local/session storage;
- success shows QBO entity IDs and idempotent counts;
- 403 reopens access dialog;
- concurrent execution state disables buttons.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location frontend
pnpm exec vitest run src/features/qbo/QboAccessDialog.test.tsx src/features/qbo/QboPage.test.tsx
```

- [ ] **Step 3: Implement the QBO workflow**

Replace plan-only copy with:

1. `Build validated plan`;
2. show exact entity counts and payload kinds;
3. `Unlock Sandbox sync`;
4. explicit checkbox “I understand this writes to the dedicated BrightFix QBO Sandbox”;
5. `Execute Sandbox sync`;
6. result table with status, QBO entity ID, safe error, and retry action.

- [ ] **Step 4: Update reconciliation UX**

Remove the pasted-report JSON editor. Add date controls, `Fetch QBO cash-basis P&L & reconcile`, loading state, exact-zero success state, and difference table.

- [ ] **Step 5: Verify rendered behavior**

Run:

```powershell
pnpm test -- --run
pnpm build
```

Then use the Browser plugin against local mock-backed endpoints. Verify desktop and mobile page identity, no blank/error overlay, console health, access dialog focus, confirmation behavior, result tables, and screenshots.

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/src/features/qbo frontend/src/features/reconciliation frontend/src/api/client.ts frontend/src/types.ts frontend/src/styles.css
git commit -m "Add gated QBO sandbox sync experience"
```

---

### Task 14: Implement Verified Weekly Reset

**Files:**
- Create: `backend/app/services/demo_reset.py`
- Modify: `backend/app/api/demo.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_demo_reset.py`
- Test: `backend/tests/integration/test_demo_reset_api.py`

**Interfaces:**
- Produces:
  - `DemoResetService.reset(now: datetime) -> ResetRun`
  - `POST /api/v1/demo/admin/reset`
  - reset status in `GET /api/v1/demo/status`.

- [ ] **Step 1: Write failing cleanup-scope tests**

Assert:

- only succeeded outbox items with QBO entity ID, sync token, kind, idempotency key, and `FinzDemo:` marker are deletion candidates;
- an unknown or partially identified QBO entity is never deleted;
- QBO deletion failure stops application-data deletion and records a retryable reset run;
- successful QBO cleanup clears shared uploads, transactions, classifications, pipeline contexts, outbox, sync runs, reconciliation runs, audit events, expired grants, and leases;
- QBO connection and account configuration remain;
- repeated reset is idempotent.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_demo_reset.py tests/integration/test_demo_reset_api.py -q
```

- [ ] **Step 3: Implement reset ordering**

Order:

1. authenticate `X-Finz-Cleanup-Token` using a stored hash;
2. acquire reset lease;
3. list verified Finz-created outbox entities;
4. delete each from QBO using stored kind/ID/sync token;
5. mark deletion results;
6. clear shared application collections in a bounded repository method;
7. create a fresh reset status with next reset time;
8. release lease.

- [ ] **Step 4: Verify and commit**

```powershell
& ..\.venv312\Scripts\python.exe -m pytest tests/unit/test_demo_reset.py tests/integration/test_demo_reset_api.py tests/unit/test_secure_logging.py -q
git add -- backend/app/services/demo_reset.py backend/app/api/demo.py backend/app/main.py backend/tests/unit/test_demo_reset.py backend/tests/integration/test_demo_reset_api.py backend/tests/unit/test_secure_logging.py
git commit -m "Add scoped weekly demo reset"
```

---

### Task 15: Add Render, GitHub Pages, and Weekly Action Configuration

**Files:**
- Create: `backend/Dockerfile`
- Create: `render.yaml`
- Create: `.github/workflows/deploy-pages.yml`
- Create: `.github/workflows/weekly-demo-reset.yml`
- Modify: `.gitignore`
- Test: local Docker build and workflow/static build verification

**Interfaces:**
- Produces:
  - Render service `finz-ledger-bridge-api`;
  - GitHub Pages artifact;
  - Sunday `03:17 UTC` reset invocation.

- [ ] **Step 1: Add a production backend container**

`backend/Dockerfile` must use Python 3.12 slim, install requirements without cache, run as a non-root user, expose no fixed host port, and start:

```dockerfile
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
```

One worker is deliberate because the free service is single-instance and the access-attempt limiter is in memory; durable business state remains in Atlas.

- [ ] **Step 2: Add Render Blueprint**

`render.yaml` defines one free web service rooted at `backend`, health path `/health`, Docker runtime, auto-deploy from `main`, and names only non-secret environment values. Secret values use `sync: false`.

- [ ] **Step 3: Add Pages workflow**

Build with:

```yaml
env:
  VITE_API_BASE_URL: ${{ vars.FINZ_PUBLIC_API_URL }}
```

Use `actions/configure-pages`, upload `frontend/dist`, and deploy with `actions/deploy-pages`. Grant only `contents: read`, `pages: write`, and `id-token: write`.

- [ ] **Step 4: Add weekly reset workflow**

Use:

```yaml
on:
  schedule:
    - cron: "17 3 * * 0"
  workflow_dispatch:
```

Call `${{ vars.FINZ_PUBLIC_API_URL }}/api/v1/demo/admin/reset` with repository secret `FINZ_CLEANUP_TOKEN`. Fail the workflow on non-2xx and never echo the token.

- [ ] **Step 5: Verify deployment artifacts locally**

Run:

```powershell
docker build -f backend\Dockerfile -t finz-ledger-bridge-api:test backend
pnpm --dir frontend build
git diff --check
```

Expected: image and static build succeed; no secret values appear in tracked files.

- [ ] **Step 6: Commit**

```powershell
git add -- backend/Dockerfile render.yaml .github/workflows/deploy-pages.yml .github/workflows/weekly-demo-reset.yml .gitignore
git commit -m "Add free cloud deployment configuration"
```

---

### Task 16: Document Setup, Operations, and Interviewer Flow

**Files:**
- Create: `docs/cloud-deployment.md`
- Create: `docs/cloud-demo-runbook.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/demo-script.md`
- Modify: `docs/ai-usage.md`

**Interfaces:**
- Produces a zero-secret operator checklist and an interviewer-safe demo path.

- [ ] **Step 1: Document the intentional demo boundary**

Explain that the shared anonymous workspace is an evaluation choice. List authentication, RBAC, tenant-scoped repository keys, object-storage isolation, retention policy, and compliance controls as production extensions.

- [ ] **Step 2: Document manual cloud setup without values**

List these user-owned actions:

1. create an Atlas Free cluster and application database user;
2. allow only the Render service’s published outbound CIDR ranges;
3. create the Render service from `render.yaml`;
4. enter all Render secrets directly in its dashboard;
5. configure GitHub Pages and repository variable `FINZ_PUBLIC_API_URL`;
6. add GitHub secret `FINZ_CLEANUP_TOKEN`;
7. add the Render HTTPS callback URI in Intuit Development Keys & OAuth;
8. call the owner-only admin-connect endpoint without printing the admin code, open its returned Intuit URL, and complete one BrightFix Sandbox OAuth authorization;
9. create/restrict a Gemini auth key and enter it only in Render;
10. send the separate demo sync access code to the interviewer.

Do not include real values or screenshots containing credentials.

- [ ] **Step 3: Update the complete demo script**

The interviewer path is:

1. read and acknowledge the shared-demo warning;
2. upload and process the workbook;
3. review and approve the three Customer Refunds;
4. verify the internal P&L;
5. build the QBO plan;
6. enter the emailed access code;
7. confirm and execute the Sandbox sync;
8. inspect stored QBO IDs and idempotent re-run behavior;
9. fetch the QBO cash-basis P&L;
10. verify exact zero-cent reconciliation.

- [ ] **Step 4: Commit**

```powershell
git add -- README.md docs/cloud-deployment.md docs/cloud-demo-runbook.md docs/architecture.md docs/demo-script.md docs/ai-usage.md
git commit -m "Document the public cloud demo"
```

---

### Task 17: Pre-Write Cloud Verification Gate

**Files:**
- Test only; no production file change unless a failure proves one is required.

**Interfaces:**
- Produces evidence that cloud infrastructure and read-only external integrations work before QBO transaction authorization.

- [ ] **Step 1: Run all local tests**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest -q
Set-Location ..\frontend
pnpm test -- --run
pnpm build
```

- [ ] **Step 2: Run real local Mongo tests**

```powershell
Set-Location ..
& .\.venv312\Scripts\python.exe scripts\run_mongo_integration.py
```

- [ ] **Step 3: Push a review branch and inspect CI**

```powershell
git status --short
git diff --check
git push -u origin agent/public-cloud-demo
gh pr create --draft --base main --head agent/public-cloud-demo --title "Publish the Finz public cloud demo"
gh pr checks --watch
```

- [ ] **Step 4: Configure Atlas, Render, Pages, GitHub Actions, Intuit callback, and Gemini**

Pause only for the manual dashboard/OAuth steps listed in Task 16. Never request Atlas account passwords, Intuit passwords, OTPs, or the contents of existing local `.env`.

- [ ] **Step 5: Verify deployed read-only behavior**

Verify:

- GitHub Pages loads at the public URL;
- Render `/health` reports Mongo repository mode without exposing the URI;
- Atlas indexes exist;
- disclaimer and upload acknowledgement render;
- upload and processing survive a Render restart;
- QBO status reports connected BrightFix Sandbox;
- CompanyInfo and chart-of-accounts resolution pass;
- Gemini returns a candidate only for an unmatched synthetic transaction;
- QBO plan contains valid internal account IDs and no network write has occurred;
- scheduled reset endpoint rejects missing/incorrect cleanup tokens.

- [ ] **Step 6: Present the QBO write checkpoint**

Report mock, contract, local Mongo, cloud Atlas, browser, OAuth, CompanyInfo, and account-resolution evidence. Ask the user for explicit authorization to perform the first real Sandbox transaction sync. Do not proceed without that authorization.

---

### Task 18: First Real Sandbox Sync, Reconciliation, and Final Release

**Files:**
- Update only tests/docs if verified external behavior requires corrections.

**Interfaces:**
- Produces the first evidence-backed, real QBO Sandbox synchronization and reconciliation.

- [ ] **Step 1: Execute one bounded real Sandbox batch after authorization**

Use the cloud UI and access code. Start with one approved transaction, verify its QBO entity ID, payload marker, account mapping, and outbox status, then retry the same request and prove no second QBO entity is created.

- [ ] **Step 2: Expand to the challenge batch**

Execute remaining approved transactions, stopping on any permanent failure or accounting mismatch. Do not bulk-retry unknown errors.

- [ ] **Step 3: Pull monthly and consolidated QBO P&L reports**

Verify April, May, June, and `2026-04-01` through `2026-06-30`. Require exact account and net-profit differences of `0` cents.

- [ ] **Step 4: Test the weekly reset in manual-dispatch mode**

Run the GitHub Action manually. Verify only Finz-marked QBO entities are deleted, shared application data is empty, the BrightFix OAuth connection remains valid, and a second reset is idempotent.

- [ ] **Step 5: Run final verification**

```powershell
Set-Location backend
& ..\.venv312\Scripts\python.exe -m pytest -q
Set-Location ..\frontend
pnpm test -- --run
pnpm build
Set-Location ..
git status --short
git diff --check
gh pr checks
```

- [ ] **Step 6: Conduct public browser acceptance**

With the Browser plugin, verify desktop and mobile layouts, cold-start behavior, disclosure, upload, review, P&L, code unlock, real Sandbox sync result, reconciliation, empty/error/loading states, no framework overlay, and no relevant console errors. Save screenshots outside the repository.

- [ ] **Step 7: Independent security and accounting review**

Check that no tracked file, Git history for the branch, build log, browser bundle, API response, or screenshot contains secrets. Reconfirm that all real writes targeted the QBO Sandbox and all reconciliation differences are zero.

- [ ] **Step 8: Mark the PR ready**

Update the PR with:

- public GitHub Pages URL;
- Render health URL;
- exact test counts;
- real Atlas/QBO/Gemini verification versus mock verification;
- weekly reset result;
- known free-tier cold-start limitation;
- production controls intentionally excluded from the demo.

Do not include the demo access code in the PR. Send it to the interviewer separately.
