# Architecture

Finz Ledger Bridge uses ports and adapters around a deterministic accounting
core:

1. CSV/XLSX adapters create immutable raw records with file and row hashes.
2. Normalization converts exact source money to integer cents and quarantines
   invalid rows.
3. Deduplication and transfer matching run before classification.
4. Rules produce candidates first; an optional AI port may only propose a typed
   account/type/explanation candidate.
5. A shared validator enforces the 21-account whitelist, direction/type
   consistency, confidence, and manual-review policy.
6. Approved decisions feed cash-basis P&L and plan-only QBO outbox generation.
7. Reconciliation compares internal totals with a scoped Cash/USD QBO report at
   an exact zero-cent tolerance.

FastAPI routes call `LedgerBridgeService`; repositories are selected through a
unit-of-work interface. In-memory repositories support isolated tests and the
default demo. Async MongoDB repositories persist domain collections and
indexes. QBO and AI are external ports with fakes for tests.

The current application service retains upload bytes, duplicate/transfer
working sets, sync-run views, and reconciliation-run views in process memory.
Those orchestration resources must move to repositories before multi-process
production deployment.

QBO execution code has a separate explicit `allow_writes` gate and is not wired
to any API endpoint. The exposed sync endpoint only creates outbox plans.
