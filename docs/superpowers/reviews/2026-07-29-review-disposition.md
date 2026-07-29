# Finz Ledger Bridge review disposition

Date: 2026-07-29

Three independent read-only reviews covered backend/security,
accounting/data-engineering, and frontend/UX. The primary agent verified each
finding before changing code.

## Confirmed and fixed

| Priority | Finding | Disposition |
|---|---|---|
| P1 | Human corrections could bypass accounting invariants | One shared validator now protects deterministic, AI, and human decisions; invalid corrections return a safe 422. |
| P1 | OAuth state was process-local and callback query strings could leak | State is hashed, TTL-bound, cookie-bound, atomically consumed through the repository; callback access logging is redacted. |
| P1 | Uploads lacked strong file/archive resource bounds | Upload streaming is capped at 10 MiB; XLSX member count, member size, expanded size, and compression ratio are bounded. |
| P1 | Possible duplicates and unmatched transfers could be auto-approved or misclassified | Both paths are forced to suggested/manual-review status; unmatched transfers cannot fall through to revenue rules. |
| P1 | Classification rules did not consistently enforce transaction direction | Direction conditions are explicit and covered by tests. |
| P1 | Business decisions lacked durable audit events | Upload, processing, approval/correction, sync planning, and reconciliation events use the audit repository. |
| P1 | Transfer synchronization could emit two expense-like items | Each approved pair produces one plan-only QBO Transfer candidate from its outflow leg. |
| P1 | QBO P&L scope could be compared without verifying report metadata | Reconciliation now requires Cash basis, exact requested dates, USD, and rejects duplicate account summaries. |
| P2 | Repeated identical raw writes could conflict on ingestion timestamps | Repositories treat identical immutable source content as idempotent while preserving duplicate source rows. |
| P2 | XLSX numeric currency cells arrived as binary floats | The XLSX adapter converts only the mapped amount cell via `Decimal(str(value))`; the domain still rejects floats. |
| P1/P2 UX | Incomplete filters, unsafe optimistic correction, weak modal keyboard behavior, and mobile overflow | Added all-account and duplicate filters, cache updates, focus trap/Escape/focus return, strict QBO status parsing, visible error states, horizontal mobile navigation, and layout fixes. |
| Final P1 | Unknown QBO P&L accounts could be silently ignored | Explicit account rows that cannot map to the whitelist now fail reconciliation instead of allowing a false match. |
| Final P2 | QBO status overclaimed that no network access occurred | API and UI now state only that no **transaction-write** network access occurred; OAuth/read-only access is described separately. |
| Final P2 | README overstated amount-conservation controls | Documentation now lists the implemented immutable-amount, transfer-pair, and P&L checks and calls full double-entry posting a prerequisite. |

## Deferred deliberately

- QBO transaction execution remains disabled. Before enabling it, the
  classification version must be part of every persisted idempotency identity
  and the remote-create/local-persist crash window needs a verified recovery
  protocol.
- OAuth access/refresh tokens still need encrypted persistent storage and a
  live CompanyInfo identity check on reconnect. Existing tests use fakes.
- Bulk approval is not transactionally atomic across an entire request.
- Reconciliation run metadata and raw QBO snapshots are held by the service;
  they need repository persistence for multi-process production operation.
- Learned rules/counterparty normalization, explicit conflict quarantine, and a
  complete double-entry posting-plan layer remain later scope.
- API authentication/authorization and broad CSRF controls are required before
  any non-loopback or multi-user deployment.
- Upload mapping preview remains limited to workbook inspection because the
  backend does not yet expose a persistent preview/mapping resource.

## Rejected or reclassified

- The review labeled QBO idempotency/version handling P0. It is a mandatory
  blocker **before QBO writes**, but not a current runtime P0 because every
  sync route is plan-only and returns `execution_authorized=false`.
- Suggestions to add large learned-rule or production identity subsystems were
  not pulled into this challenge implementation because they exceed the
  approved scope and are not required for the safe local demo.
