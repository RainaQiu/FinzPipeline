from __future__ import annotations

from decimal import Decimal
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.fakes.fake_qbo import FakeQuickBooksGateway


async def _planned_item(repo, *, transaction_id="transaction-1"):
    from app.services.qbo_sync import SyncCandidate, plan_sync

    return (
        await plan_sync(
            [
                SyncCandidate(
                    transaction=SimpleNamespace(
                        id=transaction_id,
                        version=1,
                        kind="revenue",
                        amount=Decimal("12.34"),
                        bank_account="1000",
                    ),
                    approved=SimpleNamespace(account="4000", approval_status="approved"),
                )
            ],
            "realm-1",
            repo,
        )
    )[0]


def test_make_idempotency_key_uses_realm_transaction_and_version():
    from app.services.qbo_sync import make_idempotency_key

    assert make_idempotency_key("realm-1", "transaction-9", 3) == "qbo:realm-1:transaction-9:3"


@pytest.mark.asyncio
async def test_process_outbox_item_disallows_writes_before_calling_gateway():
    from app.services.qbo_sync import process_outbox_item

    gateway = FakeQuickBooksGateway()

    from app.integrations.quickbooks.protocol import QboWriteNotAuthorizedError

    with pytest.raises(QboWriteNotAuthorizedError):
        await process_outbox_item("outbox-1", gateway, object(), allow_writes=False)

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_plan_sync_creates_a_revenue_deposit_with_exact_dollar_amount():
    from app.services.qbo_sync import SyncCandidate, plan_sync

    class RecordingRepository:
        def __init__(self):
            self.items = []

        async def save_outbox_item(self, item):
            self.items.append(item)

    repo = RecordingRepository()
    candidate = SyncCandidate(
        transaction=SimpleNamespace(
            id="transaction-1",
            version=1,
            kind="revenue",
            amount=Decimal("12.34"),
            bank_account="1000",
        ),
        approved=SimpleNamespace(account="4000", approval_status="approved"),
    )

    await plan_sync([candidate], "realm-1", repo)

    assert len(repo.items) == 1
    assert repo.items[0].payload == {
        "DepositToAccountRef": {"value": "1000"},
        "Line": (
            {
                "Amount": "12.34",
                "DetailType": "DepositLineDetail",
                "DepositLineDetail": {"AccountRef": {"value": "4000"}},
            },
        ),
    }


@pytest.mark.asyncio
async def test_process_outbox_item_records_qbo_result_and_does_not_repeat_success():
    from app.integrations.quickbooks.protocol import QboCreateResult
    from app.repositories.memory import InMemoryUnitOfWork
    from app.services.qbo_sync import process_outbox_item

    repo = InMemoryUnitOfWork()
    item = await _planned_item(repo)
    gateway = FakeQuickBooksGateway(QboCreateResult(entity_id="qbo-9", sync_token="4"))

    saved = await process_outbox_item(item.id, gateway, repo, allow_writes=True)
    repeated = await process_outbox_item(item.id, gateway, repo, allow_writes=True)

    assert saved.qbo_entity_id == "qbo-9"
    assert saved.sync_token == "4"
    assert repeated.status.value == "succeeded"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_process_outbox_item_marks_timeout_retryable_with_next_attempt():
    from app.repositories.memory import InMemoryUnitOfWork
    from app.services.qbo_sync import process_outbox_item

    repo = InMemoryUnitOfWork()
    item = await _planned_item(repo, transaction_id="transaction-timeout")

    saved = await process_outbox_item(
        item.id, FakeQuickBooksGateway(TimeoutError()), repo, allow_writes=True
    )

    assert saved.status.value == "retryable_failed"
    assert saved.last_error_code == "timeout"
    assert saved.next_attempt_at is not None


@pytest.mark.asyncio
async def test_process_outbox_item_marks_missing_gateway_entity_permanent():
    from app.integrations.quickbooks.protocol import QboGatewayError
    from app.repositories.memory import InMemoryUnitOfWork
    from app.services.qbo_sync import process_outbox_item

    repo = InMemoryUnitOfWork()
    item = await _planned_item(repo, transaction_id="transaction-missing")

    saved = await process_outbox_item(
        item.id, FakeQuickBooksGateway(QboGatewayError(code="missing")), repo, allow_writes=True
    )

    assert saved.status.value == "permanent_failed"
    assert saved.next_attempt_at is None


@pytest.mark.asyncio
async def test_retry_delay_increases_with_attempt_count_and_is_capped():
    from app.services.qbo_sync import process_outbox_item

    class CapturingRepository:
        def __init__(self, item):
            self.item = item
            self.transition_kwargs = None

        async def get(self, item_id):
            return self.item

        async def transition(self, item_id, status, **kwargs):
            self.transition_kwargs = kwargs
            self.item = replace(self.item, status=status)
            return self.item

    async def delay_for(attempt_count):
        from app.repositories.memory import InMemoryUnitOfWork

        base = await _planned_item(InMemoryUnitOfWork(), transaction_id=f"retry-{attempt_count}")
        repo = CapturingRepository(
            replace(base, status=base.status.PROCESSING, attempt_count=attempt_count)
        )
        await process_outbox_item(base.id, FakeQuickBooksGateway(TimeoutError()), repo, allow_writes=True)
        return (repo.transition_kwargs["next_attempt_at"] - repo.transition_kwargs["updated_at"]).total_seconds()

    assert await delay_for(2) > await delay_for(1)
    assert await delay_for(100) == 3600
