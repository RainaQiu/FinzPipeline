# AI usage and controls

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
