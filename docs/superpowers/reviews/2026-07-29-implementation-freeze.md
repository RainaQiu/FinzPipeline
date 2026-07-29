# Finz Ledger Bridge implementation freeze

Date: 2026-07-29  
Project root: `D:\MISM\Finz`

## Implemented capability baseline

- Side-effect-free typed settings; QBO client ID, client secret, Mongo URI, and
  local passwords use secret-bearing boundaries and are never logged.
- Immutable domain records for raw rows, normalized transactions,
  classifications, ledger lines, outbox items, reconciliation, and audit.
- Strict cents/date normalization with no floating-point accounting amounts.
- Bounded CSV/XLSX ingestion, explicit field mapping, immutable source hashes,
  duplicate isolation, transfer matching, deterministic classification, review
  status, cash-basis P&L, and exact-cent reconciliation.
- Repository protocols plus concurrency-safe in-memory and real asynchronous
  MongoDB implementations.
- Plan-only QBO payload/outbox flow with whitelist validation, idempotency,
  retry state, and an explicit execution authorization boundary.
- FastAPI endpoints for uploads, processing, review/correction, reports,
  plan-only sync, and locally supplied QBO report reconciliation.
- React/Vite review workstation covering Dashboard, Upload & Mapping,
  Transaction Review, Internal P&L, QBO Sync, and Reconciliation.
- Docker MongoDB 8 bound only to `127.0.0.1:27017`, named volume
  `finz_mongodb_data`, authenticated health check, separate application user,
  fixed test database role, index initialization, and secret-safe helper scripts.

## Challenge data result

- Raw rows: 200
- Unique reviewable transactions: 195
- Exact duplicate extras: 5
- Transfer pairs: 6
- Classified transactions: 195
- Three-month revenue: 30,027,500 cents
- Three-month COGS: 9,385,000 cents
- Three-month operating expenses: 13,824,500 cents
- Three-month net profit: 6,818,000 cents

## Verification baseline

- Backend with real local MongoDB enabled:
  `python scripts\run_mongo_integration.py --all` → **178 passed in 3.41s**.
- Real Mongo repository-only suite:
  `python scripts\run_mongo_integration.py` → **6 passed in 2.27s**.
- Frontend:
  `pnpm test -- --run` → **7 passed**;
  `pnpm build` → **successful**.
- Browser:
  real local XLSX upload/process, review inspector, plan-only QBO outbox,
  reconciliation empty state, desktop rendering, and 390 px responsive rendering
  verified; no application console errors.
- Docker daemon: real, Engine 29.6.2.
- Mongo container: real `finz-mongodb`, running and healthy.
- `mongosh`: real authenticated `{ok:1}` ping.
- Persistence: fixed `finz-test-volume-marker` survived restart of only
  `finz-mongodb`, then the marker alone was removed.
- QBO: no real transaction write and no live QBO network validation in this
  implementation run. Existing OAuth and write-boundary tests use fakes/mocks.

## Principal changed areas

- `backend/app/core`, `backend/app/domain`, `backend/app/services`
- `backend/app/repositories`, `backend/app/api`, `backend/app/main.py`
- `backend/tests/unit`, `backend/tests/contract`, `backend/tests/integration`
- `frontend/`
- `compose.yaml`, `docker/mongo/init/`, `scripts/`
- `.env.example`, `.gitignore`, `backend/requirements.txt`
- `docs/local-mongodb.md`, `docs/superpowers/plans/`

## Known freeze-point gaps

- The API does not yet expose separate upload mapping/quality-report resources;
  mapping is submitted directly to the process endpoint.
- The API does not yet expose QBO account verification.
- The production app factory defaults to the in-memory unit of work unless a
  repository is injected; real Mongo repository behavior is independently
  integration-tested and local indexes are initialized.
- QBO execution remains intentionally disabled. No QBO write may be enabled
  without separate user authorization and a live safety review.
- MongoDB Atlas remains unverified and is not required for this local baseline.

This document is the input baseline for the independent review pipeline. Review
agents are read-only and must cite concrete files and line numbers.
