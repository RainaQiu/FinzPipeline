from __future__ import annotations

import json

import httpx
import pytest

from app.domain.accounts import ACCOUNT_DEFINITIONS, AccountType
from app.domain.transactions import Direction
from app.integrations.ai.protocol import AllowedAccount, ClassificationInput
from app.integrations.gemini.client import GeminiClassificationProvider


def classification_input() -> ClassificationInput:
    return ClassificationInput(
        transaction_id="sensitive-transaction-id",
        description="UNKNOWN CLOUD SERVICE",
        amount_minor=-1299,
        direction=Direction.OUTFLOW,
        transaction_date=__import__("datetime").date(2026, 5, 7),
        bank_account_number="sensitive-bank-account",
    )


def allowed_accounts() -> tuple[AllowedAccount, ...]:
    return tuple(
        AllowedAccount(number=account.number, account_type=account.account_type)
        for account in ACCOUNT_DEFINITIONS.values()
    )


def gemini_response(candidate: dict[str, object] | str) -> httpx.Response:
    text = candidate if isinstance(candidate, str) else json.dumps(candidate)
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": text}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 10,
                "totalTokenCount": 30,
            },
            "modelVersion": "gemini-test",
            "responseId": "response-test",
        },
    )


def valid_candidate() -> dict[str, object]:
    return {
        "account_number": "6030",
        "transaction_type": "operating_expense",
        "explanation": "The normalized description resembles a software subscription.",
        "confidence_basis_points": 7200,
    }


@pytest.mark.asyncio
async def test_request_uses_fixed_host_header_key_and_minimal_normalized_facts() -> None:
    """Serializing IDs, amounts, dates, or bank facts would disclose unnecessary data."""
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return gemini_response(valid_candidate())

    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.classify(classification_input(), allowed_accounts())

    assert result is not None
    assert result.account_number == "6030"
    assert observed["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.5-flash-lite:generateContent"
    )
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert headers["x-goog-api-key"] == "gemini-test-secret"
    assert "key=" not in str(observed["url"])

    body = observed["body"]
    assert isinstance(body, dict)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] == 256
    schema = body["generationConfig"]["responseJsonSchema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "account_number",
        "transaction_type",
        "explanation",
        "confidence_basis_points",
    }
    sent_facts = json.loads(body["contents"][0]["parts"][0]["text"])
    assert sent_facts["transaction"] == {
        "description_normalized": "UNKNOWN CLOUD SERVICE",
        "direction": "outflow",
    }
    assert len(sent_facts["allowed_accounts"]) == 21
    assert sent_facts["allowed_accounts"][0] == {
        "account_number": "1000",
        "account_type": "asset",
    }
    serialized = json.dumps(body)
    for forbidden in (
        "sensitive-transaction-id",
        "sensitive-bank-account",
        "amount_minor",
        "transaction_date",
        "bank_account_number",
        "qbo",
    ):
        assert forbidden not in serialized.lower()


@pytest.mark.asyncio
async def test_request_bounds_public_description_length() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["body"] = json.loads(request.content)
        return gemini_response(valid_candidate())

    transaction = classification_input()
    transaction = ClassificationInput(
        transaction_id=transaction.transaction_id,
        description="X" * 2_000,
        amount_minor=transaction.amount_minor,
        direction=transaction.direction,
        transaction_date=transaction.transaction_date,
        bank_account_number=transaction.bank_account_number,
    )
    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.classify(transaction, allowed_accounts()) is not None
    body = observed["body"]
    assert isinstance(body, dict)
    sent_facts = json.loads(body["contents"][0]["parts"][0]["text"])
    assert sent_facts["transaction"]["description_normalized"] == "X" * 256


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate",
    [
        "```json\n{}\n```",
        {**valid_candidate(), "amount_minor": -1299},
        {**valid_candidate(), "account_number": "9999"},
        {**valid_candidate(), "transaction_type": "revenue", "account_number": "4000"},
        {**valid_candidate(), "confidence_basis_points": 72.5},
    ],
)
async def test_malformed_or_unsafe_output_returns_no_candidate(
    candidate: dict[str, object] | str,
) -> None:
    """Accepting malformed or accounting-inconsistent model output would bypass validation."""
    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(lambda request: gemini_response(candidate)),
    )

    assert await provider.classify(classification_input(), allowed_accounts()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
async def test_retryable_status_is_attempted_once_more(
    status_code: int,
) -> None:
    """Giving up before the bounded retry would make transient provider failures brittle."""
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status_code, text="upstream details must stay private")
        return gemini_response(valid_candidate())

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(handler),
        sleeper=sleeper,
    )

    assert await provider.classify(classification_input(), allowed_accounts()) is not None
    assert attempts == 2
    assert delays == [0.25]


@pytest.mark.asyncio
async def test_non_retryable_status_returns_none_without_retry_or_body_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retrying rejected requests or logging their bodies could amplify failures and leak data."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            400,
            text="gemini-test-secret upstream-sensitive-response",
        )

    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.classify(classification_input(), allowed_accounts()) is None
    assert attempts == 1
    assert "gemini-test-secret" not in caplog.text
    assert "upstream-sensitive-response" not in caplog.text


@pytest.mark.asyncio
async def test_transport_failure_uses_exactly_two_attempts_and_sanitized_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unbounded retries or exception text in logs could hang requests or disclose the key."""
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(
            "gemini-test-secret must not appear in logs",
            request=request,
        )

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(handler),
        sleeper=sleeper,
    )

    assert await provider.classify(classification_input(), allowed_accounts()) is None
    assert attempts == 2
    assert delays == [0.25]
    assert "gemini-test-secret" not in caplog.text


@pytest.mark.asyncio
async def test_empty_key_disables_network_io() -> None:
    """A missing key must preserve deterministic fallback without making a network request."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return gemini_response(valid_candidate())

    provider = GeminiClassificationProvider(
        api_key="",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.classify(classification_input(), allowed_accounts()) is None
    assert called is False


@pytest.mark.asyncio
async def test_caller_cannot_expand_the_challenge_account_whitelist() -> None:
    """Treating a caller-supplied account as trusted would let model output escape the 21 accounts."""
    supplied_accounts = (
        *allowed_accounts(),
        AllowedAccount(number="9999", account_type=AccountType.ASSET),
    )
    provider = GeminiClassificationProvider(
        api_key="gemini-test-secret",
        transport=httpx.MockTransport(
            lambda request: gemini_response(
                {
                    **valid_candidate(),
                    "account_number": "9999",
                    "transaction_type": "transfer",
                }
            )
        ),
    )

    assert await provider.classify(classification_input(), supplied_accounts) is None
