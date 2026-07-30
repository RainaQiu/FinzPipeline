# Public demo deployment checklist

This is a shared BrightFix challenge demo, not a production multi-user system.
Do not upload sensitive or real financial data.

## Render secret variables

Set values only in the Render dashboard:

- `APP_BASE_URL`
- `MONGODB_URI`
- `QBO_CLIENT_ID`
- `QBO_CLIENT_SECRET`
- `QBO_REDIRECT_URI`
- `QBO_TOKEN_ENCRYPTION_KEY`
- `QBO_EXPECTED_REALM_ID`
- `FINZ_DEMO_RESET_SECRET`
- `FINZ_DEMO_ACCESS_CODE`
- `GEMINI_API_KEY`

Keep `QBO_SANDBOX_WRITES_ENABLED=false` for initial deployment. Non-secret
defaults are defined in `render.yaml`.

## Manual web-console steps

- Atlas: free cluster, dedicated app user, Render-compatible network access.
- Intuit: Development/Sandbox only; exact Render callback URI; BrightFix Home
  Services LLC only.
- Render: connect the GitHub repository, create from `render.yaml`, add secret
  values, deploy.
- GitHub Actions: repository variable `FINZ_DEMO_BASE_URL`; repository secret
  `FINZ_DEMO_RESET_SECRET`.

## Acceptance

- `/health` returns 200 and `/ready` returns ready.
- SPA deep links load directly.
- Disclaimer remains visible.
- Challenge workbook uploads and produces the internal P&L.
- QBO status names BrightFix, account preflight returns 21 accounts, and 6060
  maps to Id 114.
- QBO Cash P&L reads the exact period. `NoReportData=true` is displayed as an
  empty/unsynced report.
- No QBO write is attempted during deployment acceptance.
