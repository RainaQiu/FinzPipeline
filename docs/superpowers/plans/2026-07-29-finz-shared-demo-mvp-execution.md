# Finz Shared Public Demo MVP — Fast Deployment Execution Map

**Goal:** Publish one shared, anonymous BrightFix demonstration as quickly as possible without weakening accounting, QBO-write, secret, or persistence safety.

**Deployment decision:** Use one Render Web Service. Render builds the React frontend, then FastAPI serves the generated SPA and `/api` from the same HTTPS origin. GitHub Pages is dropped because it has not been implemented beyond CI; the single-origin path avoids a second deployment, production CORS coordination, duplicate frontend API configuration, and a second Intuit redirect URI.

## Scope Boundary

This is intentionally a shared challenge demo, not a production multi-user SaaS. The UI must state:

> Shared demonstration environment. Do not upload sensitive or real financial data. Authentication, tenant isolation, and per-user data separation are intentionally outside this challenge demo.

Retained:

- BrightFix sample upload, normalization, classification, review, cash-basis P&L, QBO Sandbox, reconciliation, and weekly shared reset.
- One shared MongoDB Atlas workspace.
- One dedicated BrightFix QBO Sandbox connection.
- Access-code plus explicit confirmation protection for any real Sandbox write.
- CI, fail-closed production settings, health checks, environment-variable secrets, and audit/outbox safety.

Cancelled or deferred:

- Registration, login, password reset, social login, RBAC, organizations, teams, multi-tenancy, per-user workspaces, per-user QBO connections, billing, email, production QBO, and unrelated UI features.
- GitHub Pages deployment.

## Original 18-Task Disposition

| Original task | Disposition |
| --- | --- |
| 1 | Retained and complete: CI baseline. |
| 2–4 | Retained and complete/current: durable shared-workspace records, repositories, restart safety, CAS, and publication gates. |
| 5, 6, 15 | Merge into MVP A: disclaimer, same-origin production settings, health/startup checks, React build, FastAPI SPA serving, Render config. |
| 14 | MVP B: weekly shared reset and short-lived demo data. |
| 7 | MVP C: access-code grants. |
| 12 | Retained in reduced form as MVP D: minimal optional Gemini runtime candidate adapter with deterministic fallback and strict validation. |
| 8, 9, 11 | Merge into MVP E: encrypted BrightFix Sandbox connection, real read-only gateway, cash-basis P&L pull and reconciliation. |
| 10, 17 | Merge into MVP F: accounting-correct outbox execution and pre-write gate. Implement and mock-test; do not perform a live write without a new explicit user authorization. |
| 13, 16, 18 plus remaining 15 work | Merge into MVP G: focused QBO/reconciliation UX, deployment documentation, cloud verification, and release gate. Task 18 live write remains authorization-gated. |

## MVP A — Single-Origin Public Runtime

- Add the public-demo disclaimer and a persistent environment badge.
- Use relative `/api` requests in production while preserving local development.
- Add fail-closed production settings for MongoDB, encryption key, QBO Sandbox credentials, access-code secret, and public base URL.
- Expose liveness and dependency-readiness separately; readiness must report unavailable when required production dependencies are absent.
- Build React during Render deployment and serve `frontend/dist` through FastAPI with SPA fallback that never shadows `/api`.
- Add `render.yaml` and CI coverage for backend tests, frontend tests, and production build.

## MVP B — Shared Workspace and Weekly Reset

- Use the existing repository abstraction with one Atlas database.
- Never claim Atlas success until startup/readiness and repository integration tests actually pass.
- Reset only shared demo/workflow collections; preserve encrypted QBO configuration.
- Protect reset with a dedicated secret and execution lease.
- Add a weekly GitHub Actions call to the reset endpoint.
- Do not retain arbitrary visitor uploads beyond the reset window.

## MVP C — Demo Access Code

- Store only hashes or short-lived grants, never the plaintext access code.
- Ordinary visitors can upload the supplied sample, browse results, review classifications, and view reconciliation.
- QBO write preparation/execution endpoints require a valid access grant and an explicit second confirmation value.
- Rate-limit or bounded-delay repeated invalid attempts without adding user accounts.

## MVP D — Minimal Gemini Candidate Adapter

- Treat Codex as a development tool only; Gemini is the challenge-required
  runtime AI integration.
- Enable Gemini only through environment variables. Missing configuration or a
  failed request must leave deterministic classification fully operational.
- Use a strict structured response schema, bounded timeout, and limited retry.
- Treat Gemini output only as an untrusted candidate and explanation.
- Revalidate account number against the 21-account whitelist; preserve original
  transaction amount and immutable fields; validate direction/type; reject
  malformed output.
- Route low-confidence or rejected candidates to human review.
- Use mock/contract tests; never print or expose an API key.

## MVP E — BrightFix QBO Sandbox Read and Reconciliation

- Encrypt access and refresh tokens at rest; redact ciphertext and tokens from repr/logs.
- Restrict Intuit endpoints and company validation to Sandbox and the expected BrightFix company/realm.
- Refresh tokens safely and persist the updated encrypted connection.
- Resolve only the approved 21-account whitelist.
- Resolve all 21 numbered accounts verified by the real Sandbox read query.
  `6060 Utilities` must reuse the existing active Expense/Utilities account
  Id `114` (USD, current balance 0); it must never create a duplicate Utilities
  account.
- Pull a Cash-basis, USD QBO P&L for an exact period and reconcile against the internal cash-basis P&L to a target difference of `$0.00`.
- Accept the verified QBO empty-report contract: `NoReportData=true` with the
  normal Income/GrossProfit/Expenses/NetOperatingIncome/NetIncome sections and
  label-only `Summary.ColData` is a valid Cash/USD report containing zero
  synced activity, not a parser error.
- Clearly label mock/demo data whenever the real Sandbox connection is unavailable.

## MVP F — Guarded Sandbox Write Path

- Preserve amount conservation, account whitelist, deterministic posting types, outbox idempotency keys, execution lease, retry state, and audit events.
- Require access grant plus explicit second confirmation.
- Mock/contract-test all QBO writes.
- Stop before the first live Sandbox transaction and request explicit user authorization with the exact entities/period/count to be written.
- Assert the complete 21-account preflight, including `6060 -> Id 114`, before
  any write. No QBO account creation or update is authorized by this plan.

## MVP G — Focused UX, Deploy, and Verify

- Keep only the demo path: disclaimer → sample upload → process → review → P&L → QBO status → reconciliation → guarded sync.
- Make loading, empty, failure, mock, real-Sandbox, and reconciliation-difference states visually explicit.
- Verify the real rendered app on desktop and basic mobile widths.
- Deploy one Render URL, verify SPA deep links, API health/readiness, upload workflow, and no browser console errors.
- Run final secret scan, backend/frontend tests, production build, and an independent QBO/accounting safety review.
- State in README/AI usage notes that Codex assisted development, Gemini
  supplies optional runtime candidates, and deterministic rules plus human
  approval control final accounting decisions.

## Minimum Human Setup

The code can be completed without these secrets, but a real public deployment requires the user to perform:

1. **MongoDB Atlas:** create/select the free cluster, create a dedicated least-privilege app user, configure network access suitable for Render, and copy the application URI into a Render secret. Do not provide an Atlas website password to Codex.
2. **Render:** connect `RainaQiu/FinzPipeline`, create the service from `render.yaml`, and set the documented secret environment variables. Never paste secret values into Git or chat.
3. **Intuit Developer:** add the exact Render HTTPS callback URI, keep the app in Development/Sandbox mode, and confirm the connected company is BrightFix Home Services LLC.
4. **Demo access:** create a strong access code and keep it outside Git; send it separately to interviewers.
5. **Live Sandbox write:** review the pre-write summary and explicitly authorize the first write in a new instruction. Deployment alone does not authorize a QBO transaction.

## Verification Boundary

- `mock/in-memory passed` is not `real Atlas passed`.
- `QBO CompanyInfo/read passed` is not `QBO write passed`.
- A Render deployment is complete only after the public URL, SPA deep links, API health, readiness, and browser demo flow are exercised.
- Missing required production configuration must fail closed with a precise, secret-free diagnostic.
