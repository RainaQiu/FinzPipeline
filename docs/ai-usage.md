# AI usage and controls

AI is optional and subordinate to deterministic accounting logic. It may
receive sanitized transaction context and return only a typed candidate:

- one account from the fixed 21-account chart;
- one supported transaction type;
- confidence in basis points;
- a short explanation.

AI does not create IDs, alter raw data, parse money, deduplicate, match
transfers, approve high-risk items, calculate reports, or send QBO requests.
Every candidate passes the same schema, whitelist, direction/type, and review
validator used by rule and human decisions. AI-only and low-confidence results
remain in manual review.

The implementation works with the AI provider disabled. Tests use fakes and do
not send challenge data to an external model.
