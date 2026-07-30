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
6. Approved decisions feed cash-basis P&L and guarded, idempotent QBO outbox generation.
7. Reconciliation compares internal totals with a scoped Cash/USD QBO report at
   an exact zero-cent tolerance.

FastAPI routes call `LedgerBridgeService`; repositories are selected through a
unit-of-work interface. In-memory repositories support isolated tests and the
default demo. Async MongoDB repositories persist domain collections and
indexes. QBO and AI are external ports with fakes for tests.

The deadline Render profile uses the in-memory repository so it can be
demonstrated without cloud credentials. The MongoDB implementation persists
uploads, normalized transactions, decisions, pipeline contexts, sync runs,
outbox items, OAuth state, encrypted QBO connection metadata, access grants,
audit events, and reconciliation runs.

QBO execution is wired only through a guarded Sandbox endpoint. It requires a
server-side write-enable flag, one-time access grant, exact confirmation,
account preflight, an item preview, execution lease, and the lower-level
`allow_writes` gate. The public deadline profile supplies no QBO credentials
and keeps writes disabled.
