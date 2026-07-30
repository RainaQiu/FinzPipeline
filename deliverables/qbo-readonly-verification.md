# QuickBooks Read-Only Report Verification

Company: BrightFix Home Services LLC  
Environment: QuickBooks Online Development Sandbox  
Currency: USD  
Accounting standard: GAAP  
Report basis: Cash

## Verified Sandbox setup

Read-only API Explorer queries verified:

- CompanyInfo for BrightFix Home Services LLC.
- All 21 required active numbered accounts.
- Existing `6060 Utilities` uses QBO internal account ID `114`; no duplicate
  Utilities account should be created.
- ProfitAndLoss report access for 2026-04-01 through 2026-06-30.

## Verified QBO P&L response

The verified report header contained:

| Field | Value |
| --- | --- |
| ReportName | ProfitAndLoss |
| ReportBasis | Cash |
| StartPeriod | 2026-04-01 |
| EndPeriod | 2026-06-30 |
| Currency | USD |
| AccountingStandard | GAAP |
| NoReportData | true |

The response contained valid Income, GrossProfit, Expenses,
NetOperatingIncome, and NetIncome sections. Their summary columns contained
labels without amount values, which is the expected QBO shape when no
transactions have been posted.

## Reconciliation status

A completed real-QBO reconciliation is not claimed. No challenge transactions
have been written to the Sandbox, so QBO currently reports zero data while the
internal consolidated P&L reports net profit of $68,180.00.

The application parser treats `NoReportData=true` as a valid empty report, not
as a parsing failure. After approved transactions are posted, the required
completion procedure is:

1. Pull Cash-basis QBO P&L for April, May, June, and the full three-month
   period.
2. Compare every included account and net profit against the internal P&L.
3. Require an exact difference of $0.00.
4. Record application amount, QBO amount, difference, status, and diagnostic
   explanation for any mismatch.

This file documents a real read-only QBO verification. It does not relabel a
mock report or internal result as a completed QBO reconciliation.
