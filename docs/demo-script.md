# Local demo script

1. Start the backend and frontend using the commands in the root README.
2. Open `http://localhost:5173`.
3. On **Upload & Mapping**, select
   `Finz Accounting Data Engineering Challenge Dataset.xlsx`, retain the
   supplied mapping, upload, and process.
4. Confirm 200 raw rows, 195 unique transactions, five duplicate extras, six
   transfer pairs, and 195 classifications.
5. On **Transaction Review**, filter by review status, duplicate status, or any
   of the 21 accounts. Open an item, inspect evidence, and exercise the
   correction dialog.
6. On **Internal P&L**, select 2026-04-01 through 2026-06-30. Confirm revenue
   30,027,500 cents, COGS 9,385,000 cents, operating expenses 13,824,500 cents,
   and net profit 6,818,000 cents.
7. On **QBO Sync**, create a plan and confirm the UI reports plan-only mode and
   `execution_authorized=false`. Do not attempt a real QBO write.
8. On **Reconciliation**, supply a Cash/USD report snapshot for the same exact
   period. A valid matching snapshot shows zero-cent differences.

For a database-backed demo, follow `docs/local-mongodb.md`. This validates local
MongoDB only; it does not validate MongoDB Atlas or a live QBO transaction.
