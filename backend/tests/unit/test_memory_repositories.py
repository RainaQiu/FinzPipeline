"""Contract tests for the local, concurrency-safe repository implementation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from app.domain.accounting import OutboxItem, OutboxStatus
from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.transactions import Direction, NormalizedTransaction, RawRecord
from app.repositories.memory import InMemoryUnitOfWork
from app.repositories.protocols import AuditEvent, ImmutableRecordError, OAuthStateExpiredError


def _raw(record_id: str = "raw-1", value: str = "10.00") -> RawRecord:
    return RawRecord(
        id=record_id,
        source_filename="bank.csv",
        source_file_sha256="a" * 64,
        source_sheet="CSV",
        source_row_number=2,
        raw_values={"Amount": value},
        raw_row_sha256="b" * 64,
        ingested_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def _decision(decision_id: str = "decision-1") -> ClassificationDecision:
    return ClassificationDecision(
        id=decision_id,
        transaction_id="tx-1",
        account_number="6000",
        transaction_type=TransactionType.OPERATING_EXPENSE,
        source=DecisionSource.HARD_RULE,
        confidence_basis_points=10000,
        approval_status=ApprovalStatus.APPROVED,
        needs_review=False,
        explanation="Known expense.",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def _outbox(item_id: str = "outbox-1", key: str = "qbo:realm:tx-1:1") -> OutboxItem:
    return OutboxItem(
        id=item_id,
        realm_id="realm",
        transaction_id="tx-1",
        classification_decision_id="decision-1",
        classification_version=1,
        idempotency_key=key,
        payload_kind="Purchase",
        payload={"amount_minor": 1000},
        status=OutboxStatus.PENDING,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def _transaction(transaction_id: str = "tx-1", *, raw_id: str = "raw-1") -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction_id,
        raw_record_id=raw_id,
        bank_transaction_id=f"bank-{transaction_id}",
        transaction_date=date(2026, 4, 1),
        posted_date=date(2026, 4, 2),
        description_original="Office supplies",
        description_normalized="office supplies",
        amount_minor=-1000,
        currency="USD",
        direction=Direction.OUTFLOW,
        bank_account_number="1000",
    )


@pytest.mark.asyncio
async def test_raw_records_are_insert_only_and_idempotent_for_identical_content():
    uow = InMemoryUnitOfWork()
    first = await uow.raw_records.add(_raw())
    repeated = await uow.raw_records.add(_raw())

    assert repeated == first
    assert await uow.raw_records.get("raw-1") == first
    with pytest.raises(ImmutableRecordError):
        await uow.raw_records.add(_raw(value="11.00"))


@pytest.mark.asyncio
async def test_raw_record_retry_ignores_new_ingestion_timestamp():
    uow = InMemoryUnitOfWork()
    first = await uow.raw_records.add(_raw())
    retry = replace(first, ingested_at=datetime(2026, 4, 2, tzinfo=timezone.utc))

    assert await uow.raw_records.add(retry) == first


@pytest.mark.asyncio
async def test_concurrent_classification_appends_allocate_unique_versions_in_order():
    uow = InMemoryUnitOfWork()

    decisions = await asyncio.gather(
        *(uow.classifications.append(_decision(f"decision-{index}")) for index in range(1, 21))
    )

    assert sorted(decision.version for decision in decisions) == list(range(1, 21))
    assert (await uow.classifications.latest("tx-1")).version == 20
    assert [item.version for item in await uow.classifications.history("tx-1")] == list(range(1, 21))


@pytest.mark.asyncio
async def test_outbox_idempotency_and_concurrent_claim_allow_only_one_worker():
    uow = InMemoryUnitOfWork()
    first = await uow.outbox.add(_outbox())
    assert await uow.outbox.add(_outbox("other-id")) == first

    claims = await asyncio.gather(*(uow.outbox.claim_pending(limit=1) for _ in range(10)))

    claimed = [item for batch in claims for item in batch]
    assert [item.id for item in claimed] == ["outbox-1"]
    assert claimed[0].status is OutboxStatus.PROCESSING
    assert claimed[0].attempt_count == 1


@pytest.mark.asyncio
async def test_oauth_state_is_hashed_expiring_and_consumable_once():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    saved = await uow.oauth_states.put("opaque-state", expires_at=now.replace(hour=1))

    assert saved.state_hash != "opaque-state"
    assert not hasattr(saved, "state")
    assert await uow.oauth_states.consume("opaque-state", now=now) == saved
    assert await uow.oauth_states.consume("opaque-state", now=now) is None

    await uow.oauth_states.put("expired", expires_at=now)
    with pytest.raises(OAuthStateExpiredError):
        await uow.oauth_states.consume("expired", now=now.replace(hour=2))


@pytest.mark.asyncio
async def test_concurrent_oauth_state_consumption_returns_one_winner():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    await uow.oauth_states.put("one-use", expires_at=now.replace(hour=1))

    values = await asyncio.gather(
        *(uow.oauth_states.consume("one-use", now=now) for _ in range(10))
    )

    assert sum(value is not None for value in values) == 1


@pytest.mark.asyncio
async def test_transactions_filter_and_paginate_without_exposing_mutable_storage():
    uow = InMemoryUnitOfWork()
    await uow.transactions.add(_transaction("tx-1", raw_id="raw-1"))
    await uow.transactions.add(_transaction("tx-2", raw_id="raw-2"))

    assert await uow.transactions.get("missing") is None
    assert [item.id for item in await uow.transactions.list(raw_record_id="raw-2")] == ["tx-2"]
    assert [item.id for item in await uow.transactions.list(offset=1, limit=1)] == ["tx-2"]


@pytest.mark.asyncio
async def test_outbox_only_permits_valid_transitions_after_claiming():
    uow = InMemoryUnitOfWork()
    await uow.outbox.add(_outbox())
    with pytest.raises(ValueError):
        await uow.outbox.transition("outbox-1", OutboxStatus.SUCCEEDED)

    await uow.outbox.claim_pending()
    completed = await uow.outbox.transition("outbox-1", OutboxStatus.SUCCEEDED)
    assert completed.status is OutboxStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_audit_events_receive_stable_append_order_and_page_independently():
    uow = InMemoryUnitOfWork()
    first = await uow.audit.append(
        AuditEvent("raw.ingested", {"raw_id": "raw-1"}, datetime(2026, 4, 1, tzinfo=timezone.utc))
    )
    second = await uow.audit.append(
        AuditEvent("transaction.normalized", {"transaction_id": "tx-1"}, datetime(2026, 4, 1, tzinfo=timezone.utc))
    )

    assert (first.sequence, second.sequence) == (1, 2)
    assert await uow.audit.list(offset=1) == (second,)


@pytest.mark.asyncio
async def test_unit_of_work_exposes_all_repositories_through_an_async_context():
    async with InMemoryUnitOfWork() as uow:
        assert uow.raw_records is not None
        assert uow.transactions is not None
        assert uow.classifications is not None
        assert uow.outbox is not None
        assert uow.audit is not None
        assert uow.oauth_states is not None
