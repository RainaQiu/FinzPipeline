# Finz Ledger Bridge - Submission Index

Finz Ledger Bridge is an accounting data pipeline for the BrightFix Home
Services challenge dataset. It preserves raw bank records, normalizes exact
money and dates, detects duplicates and transfers, classifies transactions,
routes uncertain items to human review, calculates cash-basis P&L, prepares
idempotent QBO outbox items, and compares internal totals with a scoped QBO
Cash-basis Profit and Loss report.

## Primary links

- **Source repository:** https://github.com/RainaQiu/FinzPipeline
- **Public demonstration:** https://finz-public-demo.onrender.com
- **Submission PDF:**
  [deliverables/Finz_Ledger_Bridge_Submission.pdf](deliverables/Finz_Ledger_Bridge_Submission.pdf)
- **Setup and technical documentation:** [README.md](README.md)
- **AI usage note:** [docs/ai-usage.md](docs/ai-usage.md)
- **Architecture:** [docs/architecture.md](docs/architecture.md)
- **Demonstration script:** [docs/demo-script.md](docs/demo-script.md)
- **Internal P&L statements:**
  [deliverables/internal-pnl-statements.md](deliverables/internal-pnl-statements.md)
- **QBO read-only verification:**
  [deliverables/qbo-readonly-verification.md](deliverables/qbo-readonly-verification.md)

The Render free instance may sleep after inactivity; the first request can
take approximately 50 seconds.

## Deliverables

### Source-code repository

The repository contains the React frontend, FastAPI backend, deterministic
accounting domain, in-memory and MongoDB repositories, constrained Gemini
adapter, QBO Sandbox adapter, Docker MongoDB setup, tests, CI, and Render
deployment blueprint.

### Working application and setup instructions

The public URL runs a zero-secret shared demonstration profile. It supports
the challenge upload, configurable field mapping, normalization,
duplicate/transfer detection, review, and internal P&L workflow. Local and
full-cloud setup instructions are in [README.md](README.md),
[docs/local-mongodb.md](docs/local-mongodb.md), and
[docs/deployment-checklist.md](docs/deployment-checklist.md).

### Internal P&L

The application generates Cash-basis monthly and consolidated P&L statements
with account-level drill-down. The golden challenge period is 2026-04-01
through 2026-06-30. The complete monthly and consolidated totals are recorded
in
[deliverables/internal-pnl-statements.md](deliverables/internal-pnl-statements.md).
The verified consolidated totals are:

| Metric | Amount |
| --- | ---: |
| Revenue | $300,275.00 |
| Cost of Goods Sold | $93,850.00 |
| Gross Profit | $206,425.00 |
| Operating Expenses | $138,245.00 |
| Net Profit | $68,180.00 |

Transfers, owner activity, duplicate extras, and fixed-asset purchases are
excluded from the P&L.

### QuickBooks P&L and reconciliation

The QBO report parser and reconciliation workflow require Cash basis, USD, and
an exact requested period. Reconciliation tolerance is $0.00 for every account
and net profit.

The BrightFix Sandbox CompanyInfo, all 21 active numbered accounts, and the
Cash-basis ProfitAndLoss API were verified through read-only QBO requests.
`6060 Utilities` reuses existing QBO internal account ID `114`.

The current QBO P&L is a valid empty response with `NoReportData=true` because
no challenge transactions have been posted. Therefore this submission does
not claim a completed real-QBO transaction reconciliation. No mock result is
presented as a real QBO result. The verified read-only response and remaining
gap are documented in
[deliverables/qbo-readonly-verification.md](deliverables/qbo-readonly-verification.md).

### Screen recording

The short recording is supplied separately with the submission. It shows the
public application's upload, normalization, classification review, internal
P&L, guarded QBO boundary, and reconciliation interface. The narration
explicitly distinguishes working public-demo behavior from integrations that
require secrets or a real Sandbox write.

### AI usage

[docs/ai-usage.md](docs/ai-usage.md) identifies the development tools, the
runtime Gemini boundary, AI-generated work, deterministic safeguards, and the
items independently validated by the developer.

## Demonstration safety statement

This is a shared challenge demonstration, not a production multi-user
financial system. Do not upload sensitive or real financial data.
Authentication, tenant isolation, RBAC, privacy controls, durable cloud
persistence, and operational monitoring would be required before production
use.

QBO Production is prohibited. QBO Sandbox writes are disabled in the public
deployment, and no real QBO transaction write is claimed.
