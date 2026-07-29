# Delivery file manifest

This manifest records the Finz Ledger Bridge implementation surface created or
modified during the 2026-07-29 implementation and review pipeline.

## Root, operations, and documentation

- `.env.example`, `.gitignore`, `compose.yaml`, `README.md`
- `docker/mongo/init/01-create-app-user.js`
- `scripts/ensure_local_mongodb_secrets.py`
- `scripts/ensure_local_mongodb_test_role.py`
- `scripts/init_mongodb_indexes.py`
- `scripts/mongosh_ping.py`
- `scripts/run_mongo_integration.py`
- `scripts/verify_mongodb_persistence.py`
- `docs/local-mongodb.md`
- `docs/architecture.md`, `docs/ai-usage.md`, `docs/demo-script.md`
- `docs/superpowers/plans/2026-07-29-finz-ledger-bridge-implementation.md`
- `docs/superpowers/reviews/2026-07-29-implementation-freeze.md`
- `docs/superpowers/reviews/2026-07-29-review-disposition.md`

## Backend application

- `backend/requirements.txt`, `backend/pytest.ini`
- `backend/app/main.py`, `backend/app/config.py`
- `backend/app/core/config.py`, `backend/app/core/errors.py`,
  `backend/app/core/logging.py`
- `backend/app/domain/accounts.py`, `backend/app/domain/accounting.py`,
  `backend/app/domain/classification.py`, `backend/app/domain/rules.py`,
  `backend/app/domain/transactions.py`
- `backend/app/services/classification.py`,
  `backend/app/services/deduplication.py`,
  `backend/app/services/ingestion.py`,
  `backend/app/services/ledger_bridge.py`,
  `backend/app/services/normalization.py`, `backend/app/services/pnl.py`,
  `backend/app/services/qbo_sync.py`,
  `backend/app/services/reconciliation.py`,
  `backend/app/services/transfers.py`
- `backend/app/repositories/protocols.py`,
  `backend/app/repositories/memory.py`,
  `backend/app/repositories/mongo.py`
- `backend/app/integrations/ai/protocol.py`
- `backend/app/integrations/quickbooks/protocol.py`,
  `backend/app/integrations/quickbooks/client.py`
- `backend/app/api/classifications.py`,
  `backend/app/api/dependencies.py`, `backend/app/api/errors.py`,
  `backend/app/api/health.py`, `backend/app/api/qbo_oauth.py`,
  `backend/app/api/qbo_sync.py`, `backend/app/api/reconciliations.py`,
  `backend/app/api/reports.py`, `backend/app/api/transactions.py`,
  `backend/app/api/uploads.py`

## Backend tests and fixtures

- `backend/tests/test_app.py`
- `backend/tests/contract/test_qbo_payloads.py`
- `backend/tests/fakes/fake_qbo.py`
- `backend/tests/fixtures/golden_dataset.py`
- `backend/tests/integration/test_api_errors.py`
- `backend/tests/integration/test_api_workflow.py`
- `backend/tests/integration/test_golden_ingestion.py`
- `backend/tests/integration/test_mongo_persistence.py`
- `backend/tests/integration/test_mongo_repositories.py`
- `backend/tests/unit/test_ai_validation.py`
- `backend/tests/unit/test_classification.py`
- `backend/tests/unit/test_config.py`
- `backend/tests/unit/test_deduplication.py`
- `backend/tests/unit/test_domain_models.py`
- `backend/tests/unit/test_ingestion.py`
- `backend/tests/unit/test_memory_repositories.py`
- `backend/tests/unit/test_normalization.py`
- `backend/tests/unit/test_pnl.py`
- `backend/tests/unit/test_qbo_sync.py`
- `backend/tests/unit/test_reconciliation.py`
- `backend/tests/unit/test_secure_logging.py`
- `backend/tests/unit/test_transfers.py`

## Frontend

- `frontend/package.json`, `frontend/pnpm-lock.yaml`,
  `frontend/pnpm-workspace.yaml`, `frontend/index.html`
- `frontend/tsconfig.json`, `frontend/tsconfig.app.json`,
  `frontend/tsconfig.node.json`, `frontend/vite.config.ts`
- `frontend/src/main.tsx`, `frontend/src/app.tsx`,
  `frontend/src/styles.css`, `frontend/src/types.ts`
- `frontend/src/api/client.ts`
- `frontend/src/components/AppShell.tsx`,
  `frontend/src/components/AppShell.test.tsx`,
  `frontend/src/components/ui.tsx`
- `frontend/src/features/dashboard/DashboardPage.tsx`,
  `frontend/src/features/dashboard/DashboardPage.test.tsx`
- `frontend/src/features/upload/UploadPage.tsx`,
  `frontend/src/features/upload/UploadPage.test.tsx`
- `frontend/src/features/review/ReviewPage.tsx`,
  `frontend/src/features/review/ReviewPage.test.tsx`
- `frontend/src/features/pnl/PnlPage.tsx`,
  `frontend/src/features/pnl/PnlPage.test.tsx`
- `frontend/src/features/qbo/QboPage.tsx`,
  `frontend/src/features/qbo/QboPage.test.tsx`
- `frontend/src/features/reconciliation/ReconciliationPage.tsx`,
  `frontend/src/features/reconciliation/ReconciliationPage.test.tsx`
- `frontend/src/test/render.tsx`, `frontend/src/test/setup.ts`
- `frontend/src/utils/format.ts`

Generated caches, `frontend/dist`, virtual environments, `node_modules`, local
`.env`, supplied challenge data, and supplied design/source documents are not
implementation source changes.
