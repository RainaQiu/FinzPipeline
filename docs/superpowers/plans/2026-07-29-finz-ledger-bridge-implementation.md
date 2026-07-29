# Finz Ledger Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable Finz Ledger Bridge that ingests the supplied workbook, preserves raw records, normalizes and classifies transactions deterministically, produces cash-basis P&L reports, supports reviewed/idempotent QBO synchronization through ports and an outbox, persists through interchangeable in-memory/MongoDB repositories, and exposes the challenge workflow through FastAPI and React.

**Architecture:** Domain code remains independent of FastAPI, MongoDB, QBO, and AI providers. Services orchestrate immutable raw records, normalized transactions, append-only decisions, accounting reports, outbox transitions, and reconciliation through typed repository/integration protocols. Local development uses MongoDB 8 in Docker when available; all business behavior remains executable with in-memory repositories and fake external clients.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PyMongo `AsyncMongoClient`, HTTPX, Cryptography/Fernet, pytest, React, TypeScript, Vite, TanStack Query/Table, Zod, Tailwind CSS, shadcn/ui, Vitest, React Testing Library, Playwright, Docker Compose, MongoDB 8.

## Execution status

Executed on 2026-07-29 through Tasks 1–14, including the implementation
freeze, three parallel read-only reviews, UI browser verification, final
independent verification, and confirmed-finding fixes. Final evidence:

- backend with real local Mongo integration enabled: 208 passed;
- real Mongo repository subset: 7 passed;
- frontend: 7 files / 14 tests passed and production build succeeded;
- Docker container healthy, authenticated `mongosh` ping succeeded, and named
  volume persistence survived a project-container restart;
- QBO remained plan-only: no real transaction write was attempted.

Deferred production work and exact integration boundaries are recorded in
`docs/superpowers/reviews/2026-07-29-review-disposition.md`.

## Global Constraints

- Treat `D:\MISM\Finz` as the only project root; do not initialize Git.
- Never inspect, print, log, copy, commit, or disclose values from `.env`; `.env.example` contains placeholders only.
- Never send a real QBO transaction without new explicit user authorization; all QBO write tests use fakes or intercepted HTTP.
- Preserve the supplied PDF, XLSX, CSV, existing backend files, and user-created files.
- Use Python `D:\MISM\Finz\.venv312\Scripts\python.exe` when available.
- Store monetary values as integer cents; parse via `Decimal`; never use binary floating point for accounting.
- Preserve raw records immutably and append classification/audit versions.
- Permit only the 21 challenge accounts: `1000, 1010, 1500, 3000, 4000, 4010, 4020, 4100, 5000, 5010, 6000, 6010, 6020, 6030, 6040, 6050, 6060, 6070, 6080, 6090, 6100`.
- AI may propose only typed candidate classifications and explanations; deterministic code owns IDs, dates, amounts, deduplication, transfer matching, approval, arithmetic, and sync eligibility.
- AI-only, refund, transfer, owner activity, fixed asset, possible duplicate, and ambiguous results require human review.
- MongoDB binds only to `127.0.0.1`; use a named volume, a dedicated local application user, and separate `finz_ledger_bridge` / `finz_ledger_bridge_test` databases.
- Docker cleanup is restricted to resources labeled for this project and test databases bearing the Finz test name.
- A successful API call is not accounting proof; reconciliation tolerance is exactly zero cents per account and period.
- Since the directory is not a Git repository, every “checkpoint” step records files and tests but does not run `git add`, `git commit`, or initialize Git.

## File Map

- `backend/app/core/config.py`: side-effect-free typed application settings.
- `backend/app/core/errors.py`: domain/application error codes and safe API translation.
- `backend/app/core/security.py`: token encryption and secret-redaction utilities.
- `backend/app/domain/accounts.py`: immutable 21-account whitelist and behavior metadata.
- `backend/app/domain/transactions.py`: raw and normalized transaction types.
- `backend/app/domain/classification.py`: decisions, rules, confidence, approval types.
- `backend/app/domain/accounting.py`: ledger lines, P&L, reconciliation, outbox types.
- `backend/app/services/normalization.py`: dates, descriptions, bank accounts, currencies, amounts.
- `backend/app/services/ingestion.py`: configurable CSV/XLSX parsing and immutable raw lineage.
- `backend/app/services/deduplication.py`: exact/conflict/possible duplicate decisions.
- `backend/app/services/transfers.py`: conservative two-leg transfer matching.
- `backend/app/services/classification.py`: rule precedence, confidence, risk, provider post-validation.
- `backend/app/services/pnl.py`: cash-basis P&L and drill-down aggregation.
- `backend/app/services/qbo_sync.py`: idempotency, payload planning, retry policy, outbox transitions.
- `backend/app/services/reconciliation.py`: QBO report normalization and exact comparison.
- `backend/app/repositories/protocols.py`: repository interfaces.
- `backend/app/repositories/memory.py`: deterministic in-memory repositories.
- `backend/app/repositories/mongo.py`: MongoDB implementations and indexes.
- `backend/app/integrations/ai/protocol.py`: constrained classification provider port and disabled fake.
- `backend/app/integrations/quickbooks/protocol.py`: read/write QBO port.
- `backend/app/integrations/quickbooks/client.py`: OAuth/read operations plus guarded write implementation.
- `backend/app/api/*.py`: thin FastAPI routes and schemas.
- `backend/app/main.py`: dependency wiring and lifespan.
- `backend/tests/unit/*`: pure-domain/service tests.
- `backend/tests/integration/*`: FastAPI and real Mongo tests.
- `backend/tests/contract/*`: fake/intercepted QBO contract tests; real write tests remain disabled.
- `backend/tests/fixtures/golden_dataset.py`: expected challenge counts and P&L values.
- `compose.yaml`: local MongoDB 8 service, health check, named volume, loopback binding.
- `docker/mongo/init/01-create-app-user.js`: idempotent local user/database bootstrap driven by environment.
- `frontend/*`: Vite/React review workstation.
- `README.md`, `docs/architecture.md`, `docs/ai-usage.md`, `docs/demo-script.md`: delivery documentation.

---

### Task 1: Side-effect-free configuration and domain primitives

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/errors.py`
- Create: `backend/app/domain/accounts.py`
- Create: `backend/app/domain/transactions.py`
- Create: `backend/app/domain/classification.py`
- Create: `backend/app/domain/accounting.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/unit/test_config.py`
- Test: `backend/tests/unit/test_domain_models.py`

**Interfaces:**
- Produces: `Settings.from_environment(require_qbo: bool = False) -> Settings`.
- Produces: `parse_account(number: str) -> AccountDefinition`.
- Produces immutable `RawRecord`, `NormalizedTransaction`, `ClassificationDecision`, `LedgerLine`, `OutboxItem`, and enum types used by every later task.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_settings_do_not_require_qbo_for_core(monkeypatch):
    for name in ("QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_environment(require_qbo=False)
    assert settings.mongodb_database == "finz_ledger_bridge"

def test_qbo_settings_fail_with_names_only(monkeypatch):
    monkeypatch.delenv("QBO_CLIENT_ID", raising=False)
    with pytest.raises(ConfigurationError) as error:
        Settings.from_environment(require_qbo=True)
    assert error.value.missing_names == ("QBO_CLIENT_ID",)
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_config.py -q` from `backend`.

Expected: collection or import failure because `app.core.config` does not exist.

- [ ] **Step 3: Implement minimal typed settings and account/domain models**

```python
@dataclass(frozen=True, slots=True)
class Settings:
    mongodb_uri: SecretStr
    mongodb_database: str
    qbo_client_id: SecretStr | None
    qbo_client_secret: SecretStr | None
    qbo_redirect_uri: str | None

    @classmethod
    def from_environment(cls, require_qbo: bool = False) -> "Settings":
        ...

@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    id: str
    raw_record_id: str
    bank_transaction_id: str
    transaction_date: date
    posted_date: date
    description_original: str
    description_normalized: str
    amount_minor: int
    currency: Literal["USD"]
    direction: Direction
    bank_account_number: Literal["1000", "1010"]
```

The implementation must not call `load_dotenv()` at import time and must keep secret wrappers’ string representation redacted.

- [ ] **Step 4: Test account whitelist, frozen records, enum values, and no floats**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_config.py tests/unit/test_domain_models.py -q`.

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Record the changed files and passing command in `docs/superpowers/plans/2026-07-29-finz-ledger-bridge-implementation.md`; do not initialize Git.

### Task 2: Deterministic normalization and quarantine

**Files:**
- Create: `backend/app/services/normalization.py`
- Test: `backend/tests/unit/test_normalization.py`

**Interfaces:**
- Consumes: `RawRecord`, `NormalizedTransaction`.
- Produces: `parse_amount_minor(value: object) -> int`.
- Produces: `normalize_record(raw: RawRecord, mapping: ColumnMapping) -> NormalizationResult`.

- [ ] **Step 1: Write failing examples for currency strings, Decimal values, dates, whitespace, direction, and quarantine**

```python
@pytest.mark.parametrize(
    ("source", "expected"),
    [("$3,425.00", 342500), ("($35.00)", -3500), (Decimal("-0.01"), -1)],
)
def test_parse_amount_minor_exactly(source, expected):
    assert parse_amount_minor(source) == expected

def test_non_usd_is_preserved_but_quarantined(raw_record):
    result = normalize_record(replace(raw_record, raw_values={"Currency": "CAD"}), MAPPING)
    assert result.transaction is None
    assert result.issues[0].code == "UNSUPPORTED_CURRENCY"
```

- [ ] **Step 2: Confirm failures**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_normalization.py -q`.

Expected: import failure for `app.services.normalization`.

- [ ] **Step 3: Implement Decimal-based parsing and quality issue accumulation**

Quantize to `Decimal("0.01")` with exact two-decimal validation, map `Operating Checking -> 1000`, `Tax Reserve -> 1010`, preserve original descriptions, collapse whitespace for normalized descriptions, and return all quality issues without dropping the raw record.

- [ ] **Step 4: Run normalization tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_normalization.py -q`.

Expected: PASS with tests covering missing ID/date/amount, unknown bank, out-of-range dates, and conflicting fields.

- [ ] **Step 5: Checkpoint**

Record the passing test count without a Git operation.

### Task 3: Configurable CSV/XLSX ingestion and golden fixture

**Files:**
- Create: `backend/app/services/ingestion.py`
- Create: `backend/tests/fixtures/golden_dataset.py`
- Create: `backend/tests/unit/test_ingestion.py`
- Create: `backend/tests/integration/test_golden_ingestion.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `ColumnMapping`, `IngestionPreview`, `IngestionBatch`.
- Produces: `inspect_workbook(data: bytes) -> WorkbookInspection`.
- Produces: `ingest_rows(data: bytes, filename: str, mapping: ColumnMapping) -> IngestionBatch`.

- [ ] **Step 1: Test configurable headers and immutable lineage**

```python
def test_xlsx_mapping_uses_header_row_four(dataset_bytes):
    batch = ingest_rows(dataset_bytes, DATASET_NAME, BRIGHTFIX_MAPPING)
    assert len(batch.raw_records) == 200
    assert batch.raw_records[0].source_sheet == "Raw Bank Transactions"
    assert batch.raw_records[0].source_row_number == 5
```

- [ ] **Step 2: Confirm focused failure**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_ingestion.py -q`.

- [ ] **Step 3: Implement bounded XLSX/CSV readers**

Use read-only XLSX parsing, reject macro-enabled files, enforce explicit file/sheet/row/column/size limits, compute SHA-256 for file and canonical raw row JSON, and retain formula text as untrusted input rather than executing it.

- [ ] **Step 4: Verify the supplied workbook**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/integration/test_golden_ingestion.py -q`.

Expected assertions: 3 sheets, header row 4, 200 raw rows, 195 IDs, and no mutation of the source file hash.

- [ ] **Step 5: Checkpoint**

Record the source workbook SHA-256 only; never copy workbook contents into logs beyond compact expected counts.

### Task 4: Deduplication and transfer matching

**Files:**
- Create: `backend/app/services/deduplication.py`
- Create: `backend/app/services/transfers.py`
- Test: `backend/tests/unit/test_deduplication.py`
- Test: `backend/tests/unit/test_transfers.py`
- Modify: `backend/tests/integration/test_golden_ingestion.py`

**Interfaces:**
- Produces: `deduplicate(transactions: Sequence[NormalizedTransaction]) -> DeduplicationResult`.
- Produces: `match_transfers(canonical: Sequence[NormalizedTransaction]) -> TransferMatchResult`.

- [ ] **Step 1: Write exact, conflict, possible-duplicate, and two-leg matching tests**

```python
def test_same_id_with_same_business_fields_marks_second_duplicate(tx_factory):
    result = deduplicate([tx_factory(id="a", bank_id="BF-1"), tx_factory(id="b", bank_id="BF-1")])
    assert result.canonical_ids == ("a",)
    assert result.duplicate_to_canonical == {"b": "a"}

def test_transfer_requires_opposite_accounts_signs_and_equal_amount(tx_factory):
    result = match_transfers([
        tx_factory(id="out", bank="1000", amount=-500000, description="TRANSFER REF APR-1"),
        tx_factory(id="in", bank="1010", amount=500000, description="TRANSFER REF APR-1"),
    ])
    assert result.pairs[0].transaction_ids == ("out", "in")
```

- [ ] **Step 2: Confirm failures, then implement stable ordering and conservative ambiguity handling**

Possible duplicates are annotations only. Conflicting same-ID rows and ambiguous one-to-many transfer candidates go to review; neither is silently excluded.

- [ ] **Step 3: Run unit tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_deduplication.py tests/unit/test_transfers.py -q`.

- [ ] **Step 4: Run golden assertions**

Expected: `200 raw = 195 canonical + 5 duplicate extras`; `6 transfer pairs = 12 legs`; each pair has exactly two opposite/equal legs.

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/integration/test_golden_ingestion.py -q`.

### Task 5: Deterministic classification, AI port, confidence, and approval

**Files:**
- Create: `backend/app/domain/rules.py`
- Create: `backend/app/services/classification.py`
- Create: `backend/app/integrations/ai/__init__.py`
- Create: `backend/app/integrations/ai/protocol.py`
- Test: `backend/tests/unit/test_classification.py`
- Test: `backend/tests/unit/test_ai_validation.py`
- Modify: `backend/tests/fixtures/golden_dataset.py`

**Interfaces:**
- Produces: `ClassificationProvider.classify(input, allowed_accounts) -> ClassificationProposal`.
- Produces: `classify_transaction(transaction, context, provider) -> ClassificationDecision`.
- Produces: `validate_proposal(proposal, transaction, rule_result) -> ValidatedProposal`.

- [ ] **Step 1: Write precedence, whitelist, direction, and review tests**

```python
def test_transfer_precedence_cannot_be_overridden_by_ai(transfer_tx, proposing_ai):
    decision = classify_transaction(transfer_tx, transfer_context(), proposing_ai)
    assert decision.transaction_type is TransactionType.TRANSFER
    assert decision.source is DecisionSource.HARD_RULE

def test_ai_only_decision_requires_review(expense_tx, proposing_ai):
    decision = classify_transaction(expense_tx, empty_context(), proposing_ai)
    assert decision.approval_status is ApprovalStatus.SUGGESTED
    assert decision.needs_review is True
```

- [ ] **Step 2: Confirm focused failures**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_classification.py tests/unit/test_ai_validation.py -q`.

- [ ] **Step 3: Implement data-driven rule definitions and deterministic scoring**

Rules include all mappings in design section 14.2. Confidence is derived from explicit components and clamped to 0–10000 basis points internally; provider confidence is only one input. Reject proposals with unknown accounts, changed amount/date/ID, hard-rule conflicts, wrong account behavior, or invalid schema.

- [ ] **Step 4: Verify special challenge classifications**

Expected: 1 owner contribution to 3000, 3 refunds to 4100, 1 asset purchase to 1500, 12 transfer legs excluded from P&L, and all decisions use the whitelist.

- [ ] **Step 5: Run classification tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_classification.py tests/unit/test_ai_validation.py tests/integration/test_golden_ingestion.py -q`.

### Task 6: Cash-basis P&L and exact reconciliation

**Files:**
- Create: `backend/app/services/pnl.py`
- Create: `backend/app/services/reconciliation.py`
- Test: `backend/tests/unit/test_pnl.py`
- Test: `backend/tests/unit/test_reconciliation.py`
- Modify: `backend/tests/fixtures/golden_dataset.py`
- Modify: `backend/tests/integration/test_golden_ingestion.py`

**Interfaces:**
- Produces: `build_pnl(transactions, decisions, start_date, end_date) -> ProfitAndLoss`.
- Produces: `parse_qbo_pnl(payload: Mapping[str, object]) -> QboProfitAndLoss`.
- Produces: `reconcile(internal, qbo) -> ReconciliationRun`.

- [ ] **Step 1: Write accounting invariant tests**

```python
def test_pnl_signs_and_equations(approved_lines):
    report = build_pnl(approved_lines.transactions, approved_lines.decisions, APRIL_START, APRIL_END)
    assert report.gross_profit_minor == report.total_revenue_minor - report.total_cogs_minor
    assert report.net_profit_minor == report.gross_profit_minor - report.total_operating_expenses_minor

def test_reconciliation_has_zero_tolerance():
    run = reconcile(internal_report({"4000": 100}), qbo_report({"4000": 99}))
    assert run.lines[0].difference_minor == 1
    assert run.status is ReconciliationStatus.DIFFERENCES
```

- [ ] **Step 2: Confirm failures, implement account behavior conversion, and recursive QBO row parsing**

Do not use `abs()` in the UI. Revenue/refund/COGS/expense display signs are determined in `AccountDefinition.pnl_behavior`; transfer/equity/asset accounts are rejected from P&L inputs.

- [ ] **Step 3: Generate golden expected account/month totals in the fixture**

Compute the fixture once from independently reviewed source rows and encode integer cents. Tests must assert April, May, June, and April–June account totals plus gross/net equations.

- [ ] **Step 4: Run P&L/reconciliation and golden tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_pnl.py tests/unit/test_reconciliation.py tests/integration/test_golden_ingestion.py -q`.

### Task 7: Repository protocols and in-memory implementations

**Files:**
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/app/repositories/protocols.py`
- Create: `backend/app/repositories/memory.py`
- Test: `backend/tests/unit/test_memory_repositories.py`

**Interfaces:**
- Produces: `RawRecordRepository`, `TransactionRepository`, `ClassificationRepository`, `OutboxRepository`, `AuditRepository`, `UnitOfWork` protocols.
- Produces: `InMemoryUnitOfWork`.

- [ ] **Step 1: Write repository contract tests**

```python
async def test_raw_records_are_insert_only(memory_uow, raw_record):
    await memory_uow.raw_records.add(raw_record)
    with pytest.raises(ImmutableRecordError):
        await memory_uow.raw_records.replace(raw_record.id, raw_record)

async def test_classification_versions_are_append_only(memory_uow, decision):
    first = await memory_uow.classifications.append(decision)
    second = await memory_uow.classifications.append(replace(decision, id="d2"))
    assert (first.version, second.version) == (1, 2)
```

- [ ] **Step 2: Confirm failures and implement locks for atomic in-memory operations**

Use `asyncio.Lock` around unique-key insertion, decision version allocation, OAuth state consumption, and outbox claims so concurrency behavior is testable.

- [ ] **Step 3: Test idempotent insert, append-only history, filters, pagination, outbox claim, and audit ordering**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_memory_repositories.py -q`.

### Task 8: QBO port, outbox planning, idempotency, and guarded client

**Files:**
- Create: `backend/app/integrations/quickbooks/protocol.py`
- Create: `backend/app/services/qbo_sync.py`
- Create: `backend/tests/fakes/fake_qbo.py`
- Create: `backend/tests/unit/test_qbo_sync.py`
- Create: `backend/tests/contract/test_qbo_payloads.py`
- Modify: `backend/app/integrations/quickbooks/client.py`
- Modify: `backend/app/api/qbo_oauth.py`

**Interfaces:**
- Produces: `QuickBooksGateway` protocol for CompanyInfo, accounts, reports, and guarded entity creation.
- Produces: `make_idempotency_key(realm_id, transaction_id, classification_version) -> str`.
- Produces: `plan_sync(approved_ledger, outbox_repository) -> tuple[OutboxItem, ...]`.
- Produces: `process_outbox_item(item_id, gateway, repository, allow_writes=False) -> OutboxItem`.

- [ ] **Step 1: Test keys, entity mapping, redaction, and retry classes**

```python
def test_idempotency_key_is_stable():
    assert make_idempotency_key("realm", "tx", 2) == "qbo:realm:tx:2"

async def test_processing_refuses_writes_without_explicit_gate(fake_qbo, pending_item):
    with pytest.raises(QboWriteNotAuthorizedError):
        await process_outbox_item(pending_item.id, fake_qbo, repo, allow_writes=False)
    assert fake_qbo.created_entities == []
```

- [ ] **Step 2: Confirm failures and implement planning without external writes**

Build redacted Deposit/Purchase/Transfer payload plans, save only safe account IDs/amounts/reference metadata, and never include access/refresh tokens in exceptions or audit payloads.

- [ ] **Step 3: Implement retry transitions**

Timeout, 429, and 5xx become `retryable_failed` with capped exponential delay; validation, forbidden, missing account, and accounting invariant errors become `permanent_failed`; duplicate invocation returns the existing succeeded item.

- [ ] **Step 4: Run only fake/intercepted QBO tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/unit/test_qbo_sync.py tests/contract/test_qbo_payloads.py tests/test_app.py -q`.

Expected: no network write and no sandbox mutation.

### Task 9: FastAPI application services and endpoints

**Files:**
- Create: `backend/app/api/dependencies.py`
- Create: `backend/app/api/errors.py`
- Create: `backend/app/api/uploads.py`
- Create: `backend/app/api/transactions.py`
- Create: `backend/app/api/classifications.py`
- Create: `backend/app/api/reports.py`
- Create: `backend/app/api/qbo_sync.py`
- Create: `backend/app/api/reconciliations.py`
- Create: `backend/app/api/health.py`
- Create: `backend/app/services/ledger_bridge.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_api_workflow.py`
- Test: `backend/tests/integration/test_api_errors.py`

**Interfaces:**
- Produces all endpoints in design section 22 with JSON-safe integer-cents fields.
- `create_app(settings=None, unit_of_work=None, qbo_gateway=None, ai_provider=None) -> FastAPI`.

- [ ] **Step 1: Write an in-memory API workflow test**

```python
def test_upload_process_review_and_pnl(client, dataset_path):
    upload = client.post("/api/v1/uploads", files={"file": dataset_path.open("rb")})
    processed = client.post(f"/api/v1/uploads/{upload.json()['id']}/process", json=BRIGHTFIX_MAPPING)
    assert processed.json()["counts"] == {"raw": 200, "unique": 195, "duplicates": 5}
    pnl = client.get("/api/v1/reports/pnl", params={"start_date": "2026-04-01", "end_date": "2026-06-30"})
    assert pnl.status_code == 200
```

- [ ] **Step 2: Confirm failures and implement thin routes**

Routes validate dates, mapping fields, upload bounds, account whitelist, state transitions, pagination, and correlation IDs; they call `LedgerBridgeService` rather than embedding accounting logic.

- [ ] **Step 3: Test safe errors and QBO write gate**

Assert consistent `{error: {code, message, retryable, correlation_id, details}}`, no stack traces/secrets, 409 for invalid transitions, 422 for malformed input, and 403/409 for unauthorized sync execution.

- [ ] **Step 4: Run API and existing OAuth tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/integration/test_api_workflow.py tests/integration/test_api_errors.py tests/test_app.py -q`.

### Task 10: Local MongoDB Compose, indexes, and real repository integration

**Files:**
- Create: `compose.yaml`
- Create: `docker/mongo/init/01-create-app-user.js`
- Create: `backend/app/repositories/mongo.py`
- Create: `backend/tests/integration/test_mongo_repositories.py`
- Create: `backend/tests/integration/test_mongo_persistence.py`
- Modify: `.env.example`
- Modify: `backend/requirements.txt`
- Create: `docs/local-mongodb.md`

**Interfaces:**
- Produces `MongoUnitOfWork.create_indexes()`.
- Integration tests require `FINZ_RUN_MONGO_INTEGRATION=1` and use only `finz_ledger_bridge_test`.

- [ ] **Step 1: Perform read-only environment checks**

Run:

```powershell
docker version
docker compose version
docker info
docker ps --format "{{.ID}} {{.Names}} {{.Ports}} {{.Labels}}"
Get-NetTCPConnection -LocalPort 27017 -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath 'D:\Mysoft\mongosh-2.9.2-win32-x64' -Recurse -Filter mongosh.exe
```

Do not stop any existing process/container. If 27017 belongs to another resource, select 27018 and update only Finz local configuration.

- [ ] **Step 2: Write failing Mongo repository contract tests**

Tests create unique databases named `finz_ledger_bridge_test_<run_id>`, verify indexes and repository semantics, then drop only that exact test database in `finally`.

- [ ] **Step 3: Create secure Compose configuration**

`compose.yaml` uses `mongo:8`, service/container `finz-mongodb`, `127.0.0.1:${FINZ_MONGODB_PORT:-27017}:27017`, named volume `finz_mongodb_data`, project labels, `restart: unless-stopped`, and a `mongosh --quiet --eval db.adminCommand('ping')` health check. Root/app passwords come only from `.env` substitutions and are not embedded in YAML.

- [ ] **Step 4: Ensure local secrets without displaying them**

If required local Mongo variables are missing, generate cryptographically random values and append only the missing variable assignments to `.env` through a script that never prints values. Do not read or rewrite unrelated existing lines. Validate presence by variable name/boolean only.

- [ ] **Step 5: Start and verify MongoDB**

Run `docker compose up -d mongodb`, poll `docker inspect --format "{{json .State.Health.Status}}" finz-mongodb`, and use the discovered `mongosh.exe` with a URI supplied through an environment variable so credentials do not appear in the command output.

- [ ] **Step 6: Run real repository tests**

Run: `$env:FINZ_RUN_MONGO_INTEGRATION='1'; D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest tests/integration/test_mongo_repositories.py -q`.

- [ ] **Step 7: Verify named-volume persistence non-destructively**

Insert a marker in a dedicated `finz_persistence_checks` collection, run `docker compose restart mongodb`, wait for healthy, read the marker, then delete only that marker. Do not remove the container or volume.

- [ ] **Step 8: Run all backend tests**

Run: `D:\MISM\Finz\.venv312\Scripts\python.exe -m pytest -q`.

### Task 11: React review workstation

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/features/upload/UploadPage.tsx`
- Create: `frontend/src/features/review/ReviewPage.tsx`
- Create: `frontend/src/features/pnl/PnlPage.tsx`
- Create: `frontend/src/features/qbo/QboPage.tsx`
- Create: `frontend/src/features/reconciliation/ReconciliationPage.tsx`
- Create: `frontend/src/test/*`
- Test: `frontend/src/features/**/*.test.tsx`
- Test: `frontend/e2e/demo-flow.spec.ts`

**Interfaces:**
- Consumes FastAPI endpoints from Task 9.
- Produces routes `/upload`, `/review`, `/pnl`, `/qbo`, `/reconciliation`.

- [ ] **Step 1: Use required frontend skills before code**

Read and follow `superpowers:brainstorming` only to translate the approved UX into a fixed implementation brief, then `build-web-apps:frontend-app-builder`, `build-web-apps:react-best-practices`, and `build-web-apps:shadcn`.

- [ ] **Step 2: Write failing component tests**

Tests cover file mapping preview, transaction filters, risk/confidence text labels, keyboard-operable correction dialog, P&L drill-down, loading/empty/error states, sync-disabled messaging, and reconciliation differences not conveyed by color alone.

- [ ] **Step 3: Implement the approved workflow**

Use a restrained accounting-workbench visual system, responsive tables/cards, semantic landmarks, visible focus, accessible labels, integer-cents formatting at the presentation boundary, and no accounting calculations duplicated from the backend.

- [ ] **Step 4: Run frontend tests**

Run: `pnpm test -- --run`, `pnpm build`, and `pnpm exec playwright test` from `frontend`.

- [ ] **Step 5: Browser-render and interact with every demo page**

Start backend/frontend locally, use the in-app browser skill to perform upload → mapping → review → P&L → QBO status → reconciliation, capture screenshots, inspect console/network errors, and fix functional/accessibility defects before visual polish.

### Task 12: Implementation freeze and three-way independent read-only review

**Files:**
- Create: `docs/reviews/implementation-freeze-2026-07-29.md`
- Create: `docs/reviews/backend-security-review.md`
- Create: `docs/reviews/accounting-data-review.md`
- Create: `docs/reviews/frontend-ux-review.md`

**Interfaces:**
- Consumes the runnable application and full test baseline.
- Produces evidence-backed P0/P1/P2 findings; reviewers do not modify source files.

- [ ] **Step 1: Record the freeze point**

List implemented capabilities, changed files, Docker/Mongo/QBO truth status, and exact backend/frontend test results.

- [ ] **Step 2: Dispatch three independent read-only agents in parallel**

Agent A reviews FastAPI boundaries, config, OAuth, tokens/secrets, validation, idempotency, error/log leakage, concurrency, and tests. Agent B reviews cents/signs, accounting invariants, dedupe, transfers, classification/confidence, P&L, QBO mapping, reconciliation, and lineage. Agent C reviews upload/mapping/review/reconciliation UX, errors/empty/loading states, accessibility, responsiveness, visual consistency, and demo flow.

Each finding must include severity, exact file and line, evidence/reproduction, risk, and concrete fix. Generic advice is rejected.

- [ ] **Step 3: Main-agent validation and triage**

Reproduce or inspect every finding, reject incorrect/out-of-scope items with reasons, and order confirmed work P0 → P1 → P2.

- [ ] **Step 4: Fix confirmed findings with focused failing tests**

Only the main agent integrates fixes. Run targeted tests after each finding group and the complete backend/frontend suites after all confirmed findings.

### Task 13: UI usability polish with real browser verification

**Files:**
- Modify only frontend files identified by the validated UX review.
- Test: affected component tests and `frontend/e2e/demo-flow.spec.ts`.

**Interfaces:**
- Preserves API and business scope.

- [ ] **Step 1: Fix function and usability before appearance**

Prioritize hierarchy, table readability, confidence/risk labels, review actions, loading/empty/error states, reconciliation difference explanations, and basic mobile behavior.

- [ ] **Step 2: Run affected tests and production build**

Run `pnpm test -- --run`, `pnpm build`, and Playwright.

- [ ] **Step 3: Verify rendered behavior in the browser**

Test desktop and narrow viewport interaction, keyboard focus, error recovery, and the complete demo path. Save evidence screenshots under `docs/screenshots/`; do not claim visual success from source inspection alone.

### Task 14: Final independent verification and delivery documentation

**Files:**
- Create: `docs/reviews/final-independent-verification.md`
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/ai-usage.md`
- Create: `docs/demo-script.md`
- Modify: `docs/local-mongodb.md`

**Interfaces:**
- Produces final evidence and setup instructions without secret values.

- [ ] **Step 1: Dispatch one final read-only verification agent**

The agent checks the approved design, all test results, real Mongo versus fake boundaries, secret leakage, `.gitignore`, and evidence that no QBO write occurred. It does not edit files.

- [ ] **Step 2: Resolve confirmed final findings**

The main agent adds a failing regression test, applies the minimal fix, and reruns targeted and complete suites.

- [ ] **Step 3: Scan tracked project files without reading `.env`**

Search source/config/docs/tests for obvious token/client-secret/Mongo-password patterns while explicitly excluding `.env`, binaries, virtual environments, temporary renders, and `node_modules`. Confirm `.gitignore` excludes `.env`, `.env.*` except `.env.example`, volumes, caches, and generated artifacts.

- [ ] **Step 4: Run final verification matrix**

Backend: full pytest; frontend: unit/build/Playwright; Docker: daemon/version/info; Mongo: health/mongosh/persistence/integration; QBO: existing fake OAuth and read-only status tests only unless user separately authorizes a live read. No write contract test is executed.

- [ ] **Step 5: Finish delivery docs**

Document architecture, immutable lineage, rules/AI split, duplicate prevention, account whitelist, P&L signs, QBO write gate/outbox, assumptions, known limitations, local Mongo start/stop/verify commands, demo flow, AI usage, and exact mock/real validation boundaries.

## Self-Review Results

- **Spec coverage:** Tasks 1–11 cover project/config/domain, normalization, ingestion/mapping, dedupe, transfer matching, rules/AI validation, P&L/reconciliation, repository abstractions, QBO outbox/idempotency, APIs, local Mongo, and frontend workflow. Tasks 12–14 cover the authorized multi-agent review, browser verification, security scan, and delivery evidence.
- **External safety:** No task performs a real QBO transaction write. Mongo actions are restricted to the Finz container, named volume, app databases, and uniquely named test databases.
- **Type consistency:** Money remains `int` minor units from normalization through repositories, P&L, QBO payload planning, reconciliation, API serialization, and UI formatting. Repository and integration interfaces are defined before consumers.
- **Placeholder scan:** Implementation steps define concrete files, interfaces, test examples, commands, expected states, and safety gates; no unresolved implementation placeholder is required to execute a task.
- **Current baseline:** Existing `backend/tests/test_app.py` was rerun with test-only environment values: 6 tests passed. These tests use fake QBO clients and do not validate a real QBO write or MongoDB.
