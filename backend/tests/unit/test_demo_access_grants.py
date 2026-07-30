from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.demo_access_grants import AccessGrantRequest
from app.core.config import Settings
from app.main import create_app
from app.repositories.memory import InMemoryUnitOfWork
from app.services.demo_access_grants import DemoAccessGrantService


NOW = datetime(2026, 7, 30, 1, 2, 3, tzinfo=timezone.utc)
ACCESS_CODE = "Finz-Interview-9vK2mR6x"
RAW_TOKEN = "z" * 43


def _settings() -> Settings:
    return Settings(
        mongodb_uri=SecretStr(""),
        mongodb_database="finz_test",
        repository_backend="memory",
        qbo_client_id=None,
        qbo_client_secret=None,
        qbo_redirect_uri=None,
        qbo_environment="sandbox",
        qbo_authorization_url="https://appcenter.intuit.com/connect/oauth2",
        qbo_token_url="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        qbo_base_url="https://sandbox-quickbooks.api.intuit.com/v3",
        qbo_scope="com.intuit.quickbooks.accounting",
        app_environment="development",
        public_base_url="http://localhost:8000",
        frontend_static_dir=None,
        demo_reset_secret=SecretStr("Finz-Reset-7zN4pQ8vK2mR6xC9sL3wT5yH"),
        demo_access_code=SecretStr(ACCESS_CODE),
    )


@pytest.mark.asyncio
async def test_invalid_code_uses_compare_digest_and_fixed_injected_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compared: list[tuple[str, str]] = []
    delays: list[float] = []

    def observed_compare(presented: str, expected: str) -> bool:
        compared.append((presented, expected))
        return False

    async def observed_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "app.services.demo_access_grants.compare_digest", observed_compare
    )
    service = DemoAccessGrantService(
        InMemoryUnitOfWork(),
        access_code=SecretStr(ACCESS_CODE),
        sleeper=observed_sleep,
        clock=lambda: NOW,
    )

    result = await service.issue("incorrect-code")

    assert result is None
    assert compared == [("incorrect-code", ACCESS_CODE)]
    assert delays == [0.25]


@pytest.mark.asyncio
async def test_success_issues_only_a_hash_with_short_ttl_and_consumes_once() -> None:
    uow = InMemoryUnitOfWork()
    service = DemoAccessGrantService(
        uow,
        access_code=SecretStr(ACCESS_CODE),
        sleeper=lambda _delay: _no_sleep(),
        clock=lambda: NOW,
        token_factory=lambda: RAW_TOKEN,
    )

    issued = await service.issue(ACCESS_CODE)

    assert issued is not None
    assert issued.token == f"finz_demo_{RAW_TOKEN}"
    assert issued.expires_in_seconds == 900
    expected_hash = sha256(issued.token.encode("utf-8")).hexdigest()
    assert tuple(uow.demo_grants._records) == (expected_hash,)
    assert issued.token not in repr(uow.demo_grants._records)
    assert await service.consume(issued.token, now=NOW + timedelta(minutes=14))
    assert not await service.consume(issued.token, now=NOW + timedelta(minutes=14))


@pytest.mark.asyncio
async def test_expired_grant_is_rejected() -> None:
    service = DemoAccessGrantService(
        InMemoryUnitOfWork(),
        access_code=SecretStr(ACCESS_CODE),
        sleeper=lambda _delay: _no_sleep(),
        clock=lambda: NOW,
        token_factory=lambda: RAW_TOKEN,
    )
    issued = await service.issue(ACCESS_CODE)
    assert issued is not None

    assert not await service.consume(
        issued.token, now=NOW + timedelta(seconds=900)
    )


@pytest.mark.asyncio
async def test_default_tokens_are_distinct_high_entropy_urlsafe_bearers() -> None:
    service = DemoAccessGrantService(
        InMemoryUnitOfWork(),
        access_code=SecretStr(ACCESS_CODE),
        sleeper=lambda _delay: _no_sleep(),
        clock=lambda: NOW,
    )

    first = await service.issue(ACCESS_CODE)
    second = await service.issue(ACCESS_CODE)

    assert first is not None
    assert second is not None
    assert first.token != second.token
    assert re.fullmatch(r"finz_demo_[A-Za-z0-9_-]{43}", first.token)
    assert re.fullmatch(r"finz_demo_[A-Za-z0-9_-]{43}", second.token)
    assert first.token not in repr(first)


def test_access_grant_api_returns_bearer_once_and_redacts_invalid_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    uow = InMemoryUnitOfWork()
    service = DemoAccessGrantService(
        uow,
        access_code=SecretStr(ACCESS_CODE),
        sleeper=lambda _delay: _no_sleep(),
        clock=lambda: NOW,
        token_factory=lambda: RAW_TOKEN,
    )
    app = create_app(
        settings=_settings(),
        unit_of_work=uow,
        demo_access_grant_service=service,
    )
    presented = "private-wrong-access-code"

    with TestClient(app) as client:
        rejected = client.post(
            "/api/v1/demo/access-grants",
            json={"access_code": presented},
        )
        accepted = client.post(
            "/api/v1/demo/access-grants",
            json={"access_code": ACCESS_CODE},
        )
        ordinary = client.get("/health")
        ordinary_demo_api = client.get("/api/v1/integrations/qbo/status")

    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "Access authorization failed"}
    assert presented not in rejected.text
    assert accepted.status_code == 201
    assert accepted.json() == {
        "grant_token": f"finz_demo_{RAW_TOKEN}",
        "token_type": "bearer",
        "expires_in_seconds": 900,
    }
    assert accepted.headers["cache-control"] == "no-store"
    assert "hash" not in accepted.text
    assert ordinary.status_code == 200
    assert ordinary_demo_api.status_code == 200
    assert ordinary_demo_api.json()["mode"] == "plan_only"
    assert presented not in repr(AccessGrantRequest(access_code=presented))
    assert presented not in caplog.text


async def _no_sleep() -> None:
    return None
