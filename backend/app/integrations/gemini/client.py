"""Bounded Gemini REST adapter for untrusted classification candidates."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy

import httpx
from pydantic import SecretStr, ValidationError

from app.domain.accounts import ACCOUNT_DEFINITIONS
from app.domain.classification import TransactionType
from app.domain.transactions import Direction
from app.integrations.ai.protocol import (
    AllowedAccount,
    ClassificationInput,
    ClassificationProposal,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com"
_MAX_DESCRIPTION_CHARS = 256
_MAX_OUTPUT_TOKENS = 256
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_RETRYABLE_STATUS_CODES = frozenset({408, 429, *range(500, 600)})
_TRANSACTION_TYPES = tuple(item.value for item in TransactionType)
_ACCOUNT_TYPES_BY_TRANSACTION_TYPE = {
    TransactionType.REVENUE: frozenset({"revenue"}),
    TransactionType.COGS: frozenset({"cost_of_goods_sold"}),
    TransactionType.OPERATING_EXPENSE: frozenset({"operating_expense"}),
    TransactionType.REFUND: frozenset({"contra_revenue"}),
    TransactionType.TRANSFER: frozenset({"asset"}),
    TransactionType.OWNER_ACTIVITY: frozenset({"equity"}),
    TransactionType.FIXED_ASSET: frozenset({"asset"}),
}

Sleeper = Callable[[float], Awaitable[None]]


class GeminiClassificationProvider:
    """Generate a narrow proposal while keeping deterministic code authoritative."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str,
        model: str = "gemini-3.5-flash-lite",
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if not _MODEL_PATTERN.fullmatch(model):
            raise ValueError("Gemini model name contains unsupported characters")
        self._api_key = (
            api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        )
        self._model = model
        self._transport = transport
        self._sleeper = sleeper

    async def classify(
        self,
        transaction: ClassificationInput,
        allowed_accounts: Sequence[AllowedAccount],
    ) -> ClassificationProposal | None:
        api_key = self._api_key.get_secret_value()
        if not api_key:
            return None
        canonical_accounts = tuple(
            AllowedAccount(
                number=account.number,
                account_type=ACCOUNT_DEFINITIONS[account.number].account_type,
            )
            for account in allowed_accounts
            if account.number in ACCOUNT_DEFINITIONS
        )
        if not canonical_accounts:
            return None

        request_body = _request_body(transaction, canonical_accounts)
        timeout = httpx.Timeout(15.0, connect=5.0)
        url = f"{_BASE_URL}/v1beta/models/{self._model}:generateContent"
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
        ) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        url,
                        headers={"x-goog-api-key": api_key},
                        json=request_body,
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt == 0:
                        await self._sleeper(0.25)
                        continue
                    logger.warning("Gemini candidate unavailable: transport_error")
                    return None

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt == 0:
                        await self._sleeper(0.25)
                        continue
                    logger.warning("Gemini candidate unavailable: retryable_status")
                    return None
                if not 200 <= response.status_code < 300:
                    logger.warning("Gemini candidate unavailable: request_rejected")
                    return None

                proposal = _parse_response(response)
                if proposal is None or not _is_locally_valid(
                    proposal, transaction.direction, canonical_accounts
                ):
                    logger.warning("Gemini candidate unavailable: invalid_response")
                    return None
                return proposal
        return None


def _request_body(
    transaction: ClassificationInput,
    allowed_accounts: Sequence[AllowedAccount],
) -> dict[str, object]:
    schema = deepcopy(ClassificationProposal.model_json_schema())
    schema["properties"]["account_number"]["enum"] = [
        account.number for account in allowed_accounts
    ]
    schema["properties"]["transaction_type"]["enum"] = list(_TRANSACTION_TYPES)
    prompt = {
        "transaction": {
            "description_normalized": transaction.description[:_MAX_DESCRIPTION_CHARS],
            "direction": transaction.direction.value,
        },
        "allowed_accounts": [
            {
                "account_number": account.number,
                "account_type": account.account_type.value,
            }
            for account in allowed_accounts
        ],
    }
    return {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(prompt, separators=(",", ":"))}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": _MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }


def _parse_response(response: httpx.Response) -> ClassificationProposal | None:
    try:
        payload = response.json()
        candidates = payload["candidates"]
        parts = candidates[0]["content"]["parts"]
        if len(candidates) != 1 or len(parts) != 1:
            return None
        text = parts[0]["text"]
        if not isinstance(text, str):
            return None
        return ClassificationProposal.model_validate_json(text)
    except (KeyError, IndexError, TypeError, ValueError, ValidationError):
        return None


def _is_locally_valid(
    proposal: ClassificationProposal,
    direction: Direction,
    allowed_accounts: Sequence[AllowedAccount],
) -> bool:
    accounts = {account.number: account for account in allowed_accounts}
    account = accounts.get(proposal.account_number)
    if account is None:
        return False
    try:
        transaction_type = TransactionType(proposal.transaction_type)
    except ValueError:
        return False
    if account.account_type.value not in _ACCOUNT_TYPES_BY_TRANSACTION_TYPE[
        transaction_type
    ]:
        return False
    if transaction_type is TransactionType.REVENUE:
        return direction is Direction.INFLOW
    if transaction_type in {
        TransactionType.COGS,
        TransactionType.OPERATING_EXPENSE,
        TransactionType.REFUND,
        TransactionType.FIXED_ASSET,
    }:
        return direction is Direction.OUTFLOW
    return transaction_type in {
        TransactionType.TRANSFER,
        TransactionType.OWNER_ACTIVITY,
    }
