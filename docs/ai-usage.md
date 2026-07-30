# AI usage and controls

## Tools used

- **OpenAI Codex:** development assistance for architecture translation,
  implementation, tests, documentation, deployment configuration, and
  debugging.
- **ChatGPT/Codex conversation:** requirements clarification, accounting-risk
  review, demo planning, and submission wording.
- **Gemini adapter:** optional runtime candidate classification for
  otherwise-unknown outflows. Gemini is disabled in the zero-secret public
  deployment.

## What AI generated

AI assisted with code scaffolding, domain and repository implementations,
FastAPI and React integration, automated test cases, deployment files, and
technical documentation. Runtime Gemini, when enabled, may generate only an
account/type/confidence/explanation candidate inside a strict schema.

AI did not supply or alter the challenge source data, approve accounting
decisions, create QBO credentials, authorize QBO writes, or determine final
reported amounts without deterministic validation.

## What was independently validated

The developer reviewed the approved architecture, source workbook mapping,
accounting sign conventions, P&L inclusion rules, and the 21-account
whitelist. Automated golden-data checks were used to validate source-row
counts, duplicate detection, transfer pairing, and consolidated P&L totals.

The developer also used read-only Intuit API Explorer requests to verify the
BrightFix Home Services LLC Sandbox, all 21 active numbered accounts, the
existing `6060 Utilities` mapping to QBO account ID `114`, and the QBO
Cash-basis ProfitAndLoss empty-report contract. No real QBO transaction write
or completed real-QBO reconciliation is claimed.

Codex assisted development; it is not a runtime accounting dependency.
Gemini is the optional runtime candidate classifier required by the
challenge. It is subordinate to deterministic accounting logic and may
receive only normalized minimal transaction context, never the raw upload.
It can return only a typed candidate:

- one account from the fixed 21-account chart;
- one supported transaction type;
- confidence in basis points;
- a short explanation.

AI does not create IDs, alter raw data, parse money, deduplicate, match
transfers, approve high-risk items, calculate reports, or send QBO requests.
Every candidate passes the same schema, fixed 21-account whitelist,
direction/type, and review validator used by rule and human decisions. Gemini
is consulted only for an unknown outflow after deterministic duplicate,
transfer, merchant-rule, and inflow handling. The number of calls is bounded
per upload. Every accepted AI candidate is still `suggested` and requires
human review; deterministic rules and approved human decisions are the final
authority.

`GEMINI_ENABLED` accepts only `true` or `false`. A missing key, disabled
setting, provider error, timeout, malformed response, account outside the
whitelist, or direction/type conflict preserves the deterministic/manual
fallback and does not fail the upload. Secrets are held as redacted settings
and are not logged or returned to the browser.

The implementation works with the provider disabled. Automated tests use
mock/contract transports and have not verified a real Gemini API call. If a
live smoke test is performed later, it must send only the challenge's
synthetic, minimal normalized fields (description and direction), never the
workbook, raw rows, identifiers, amounts, or sensitive financial data.
