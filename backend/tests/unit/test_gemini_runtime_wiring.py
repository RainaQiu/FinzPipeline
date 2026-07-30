from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.domain.accounts import ACCOUNT_DEFINITIONS
from app.integrations.ai.protocol import (
    ClassificationInput,
    ClassificationProposal,
    DisabledClassificationProvider,
)
from app.main import create_app
from app.repositories.memory import InMemoryUnitOfWork
from app.services.ingestion import IngestionMapping
from app.services.ledger_bridge import LedgerBridgeService
from app.services.normalization import ColumnMapping


MAPPING = IngestionMapping(
    columns=ColumnMapping(
        transaction_id="Bank ID",
        transaction_date="Date",
        posted_date="Posted",
        description="Memo",
        amount="Value",
        currency="Currency",
        bank_account="Account",
    )
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "mongodb_uri": SecretStr(""),
        "mongodb_database": "finz_test",
        "repository_backend": "memory",
        "qbo_client_id": None,
        "qbo_client_secret": None,
        "qbo_redirect_uri": None,
        "qbo_environment": "sandbox",
        "qbo_authorization_url": "https://appcenter.intuit.com/connect/oauth2",
        "qbo_token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "qbo_base_url": "https://sandbox-quickbooks.api.intuit.com/v3",
        "qbo_scope": "com.intuit.quickbooks.accounting",
        "app_environment": "development",
        "public_base_url": "http://localhost:8000",
        "frontend_static_dir": Path("missing"),
        "demo_reset_secret": None,
        "demo_access_code": None,
        "gemini_enabled": False,
        "gemini_api_key": None,
        "gemini_model": "gemini-3.5-flash-lite",
        "gemini_max_candidates_per_upload": 10,
    }
    values.update(overrides)
    return Settings(**values)


class RecordingProvider:
    def __init__(
        self,
        proposal: ClassificationProposal | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.proposal = proposal
        self.error = error
        self.calls: list[tuple[ClassificationInput, tuple[object, ...]]] = []

    async def classify(self, transaction, allowed_accounts):
        self.calls.append((transaction, tuple(allowed_accounts)))
        if self.error is not None:
            raise self.error
        return self.proposal


def _csv(*descriptions: str) -> bytes:
    rows = [
        "Bank ID,Date,Posted,Memo,Value,Currency,Account",
        *[
            f"bank-{index},2026-04-{index:02d},2026-04-{index:02d},{description},-12.34,USD,Operating Checking"
            for index, description in enumerate(descriptions, start=1)
        ],
    ]
    return ("\n".join(rows) + "\n").encode()


async def _process(service: LedgerBridgeService, data: bytes):
    upload = await service.create_upload(
        filename="checking.csv", media_type="text/csv", data=data
    )
    await service.process_upload(upload["id"], MAPPING)
    return await service.list_transactions(limit=50)


@pytest.mark.asyncio
async def test_known_rule_never_calls_gemini():
    provider = RecordingProvider(
        ClassificationProposal(
            transaction_type="operating_expense",
            account_number="6090",
            explanation="candidate",
            confidence_basis_points=7000,
        )
    )

    result = await _process(
        LedgerBridgeService(
            InMemoryUnitOfWork(),
            classification_provider=provider,
            max_ai_candidates_per_upload=10,
        ),
        _csv("ADP PAYROLL"),
    )

    assert provider.calls == []
    assert result["items"][0]["classification"]["account_number"] == "6000"


@pytest.mark.asyncio
async def test_exact_duplicate_canonical_never_calls_gemini():
    provider = RecordingProvider(
        ClassificationProposal(
            transaction_type="operating_expense",
            account_number="6090",
            explanation="candidate",
            confidence_basis_points=7000,
        )
    )
    data = (
        "Bank ID,Date,Posted,Memo,Value,Currency,Account\n"
        "same-id,2026-04-01,2026-04-01,UNKNOWN MERCHANT,-12.34,USD,Operating Checking\n"
        "same-id,2026-04-01,2026-04-01,UNKNOWN MERCHANT,-12.34,USD,Operating Checking\n"
    ).encode()

    result = await _process(
        LedgerBridgeService(
            InMemoryUnitOfWork(),
            classification_provider=provider,
            max_ai_candidates_per_upload=10,
        ),
        data,
    )

    assert provider.calls == []
    assert result["items"][0]["duplicate_status"] == "canonical"
    assert result["items"][0]["classification"]["source"] == "human"


@pytest.mark.asyncio
async def test_unknown_outflow_gets_review_only_gemini_suggestion():
    provider = RecordingProvider(
        ClassificationProposal(
            transaction_type="operating_expense",
            account_number="6090",
            explanation="General business purchase.",
            confidence_basis_points=7200,
        )
    )

    result = await _process(
        LedgerBridgeService(
            InMemoryUnitOfWork(),
            classification_provider=provider,
            max_ai_candidates_per_upload=10,
        ),
        _csv("UNFAMILIAR MERCHANT"),
    )

    decision = result["items"][0]["classification"]
    assert len(provider.calls) == 1
    assert len(provider.calls[0][1]) == 21
    assert {account.number for account in provider.calls[0][1]} == set(
        ACCOUNT_DEFINITIONS
    )
    assert decision["source"] == "ai"
    assert decision["account_number"] == "6090"
    assert decision["approval_status"] == "suggested"
    assert decision["needs_review"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    [
        RecordingProvider(error=RuntimeError("provider unavailable")),
        RecordingProvider(
            ClassificationProposal(
                transaction_type="operating_expense",
                account_number="9999",
                explanation="Not on the whitelist.",
                confidence_basis_points=6000,
            )
        ),
        RecordingProvider(
            ClassificationProposal(
                transaction_type="revenue",
                account_number="4000",
                explanation="Wrong cash direction.",
                confidence_basis_points=6000,
            )
        ),
    ],
)
async def test_provider_failure_or_invalid_proposal_keeps_manual_fallback(provider):
    result = await _process(
        LedgerBridgeService(
            InMemoryUnitOfWork(),
            classification_provider=provider,
            max_ai_candidates_per_upload=10,
        ),
        _csv("UNFAMILIAR MERCHANT"),
    )

    decision = result["items"][0]["classification"]
    assert decision["source"] == "human"
    assert decision["account_number"] == "6000"
    assert decision["approval_status"] == "suggested"


@pytest.mark.asyncio
async def test_gemini_calls_are_capped_per_upload():
    provider = RecordingProvider(None)

    result = await _process(
        LedgerBridgeService(
            InMemoryUnitOfWork(),
            classification_provider=provider,
            max_ai_candidates_per_upload=2,
        ),
        _csv("UNKNOWN ONE", "UNKNOWN TWO", "UNKNOWN THREE"),
    )

    assert result["total"] == 3
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    ("enabled", "api_key"),
    [
        (True, None),
        (False, SecretStr("test-only-key")),
    ],
)
def test_main_uses_disabled_provider_without_enabled_key_pair(enabled, api_key):
    app = create_app(
        settings=_settings(gemini_enabled=enabled, gemini_api_key=api_key),
        unit_of_work=InMemoryUnitOfWork(),
    )

    assert isinstance(app.state.ai_provider, DisabledClassificationProvider)
    assert app.state.ledger_bridge._classification_provider is app.state.ai_provider


def test_main_builds_one_enabled_provider_instance(monkeypatch):
    created: list[object] = []

    class FakeGeminiProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setattr("app.main.GeminiClassificationProvider", FakeGeminiProvider)
    app = create_app(
        settings=_settings(
            gemini_enabled=True,
            gemini_api_key=SecretStr("test-only-key"),
            gemini_max_candidates_per_upload=4,
        ),
        unit_of_work=InMemoryUnitOfWork(),
    )

    assert len(created) == 1
    assert app.state.ai_provider is created[0]
    assert app.state.ledger_bridge._classification_provider is created[0]
    assert app.state.ledger_bridge._max_ai_candidates_per_upload == 4
