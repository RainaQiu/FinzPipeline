"""Real MongoDB contract tests.

These tests are opt-in and only create databases with the
``finz_ledger_bridge_test_`` prefix.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import date, datetime, timezone
import pytest
from pymongo import AsyncMongoClient

from app.domain.accounting import OutboxItem, OutboxStatus
from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.transactions import Direction, NormalizedTransaction, RawRecord
from app.repositories.mongo import MongoUnitOfWork
from app.repositories.protocols import (
    AuditEvent,
    ImmutableRecordError,
    OAuthStateExpiredError,
)


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("FINZ_RUN_MONGO_INTEGRATION") != "1",
        reason="set FINZ_RUN_MONGO_INTEGRATION=1 to use real local MongoDB",
    ),
]


def _raw(value: str = "10.00") -> RawRecord:
    return RawRecord(
        id="raw-1",
        source_filename="bank.csv",
        source_file_sha256="a" * 64,
        source_sheet="CSV",
        source_row_number=2,
        raw_values={"Amount": value, "nested": {"labels": ["a", "b"]}},
        raw_row_sha256="b" * 64,
        ingested_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def _transaction(transaction_id: str = "tx-1") -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction_id,
        raw_record_id="raw-1",
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


def _decision(decision_id: str) -> ClassificationDecision:
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


def _outbox(item_id: str = "outbox-1") -> OutboxItem:
    return OutboxItem(
        id=item_id,
        realm_id="realm",
        transaction_id="tx-1",
        classification_decision_id="decision-1",
        classification_version=1,
        idempotency_key="qbo:realm:tx-1:1",
        payload_kind="Purchase",
        payload={"amount_minor": 1000, "lines": [{"account": "6000"}]},
        status=OutboxStatus.PENDING,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
async def mongo_uow():
    uri = os.environ["FINZ_MONGODB_URI"]
    database_name = "finz_ledger_bridge_test"
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
    uow = MongoUnitOfWork(client, database_name)
    try:
        await client.drop_database(database_name)
        await uow.create_indexes()
        yield uow
    finally:
        assert database_name == "finz_ledger_bridge_test"
        await client.drop_database(database_name)
        await client.close()


async def test_indexes_cover_lineage_versions_idempotency_and_claims(mongo_uow):
    indexes = await mongo_uow.index_information()

    assert "raw_row_sha256" in indexes["raw_records"]
    assert indexes["raw_records"]["raw_row_sha256"].get("unique") is not True
    assert indexes["transactions"]["bank_transaction_id"]["unique"] is True
    assert indexes["classifications"]["transaction_version_unique"]["unique"] is True
    assert indexes["outbox"]["idempotency_key_unique"]["unique"] is True
    assert "status_next_attempt" in indexes["outbox"]
    assert indexes["oauth_states"]["expires_at_ttl"]["expireAfterSeconds"] == 0


async def test_insert_only_records_and_domain_types_round_trip(mongo_uow):
    raw = await mongo_uow.raw_records.add(_raw())
    transaction = await mongo_uow.transactions.add(_transaction())

    assert await mongo_uow.raw_records.add(_raw()) == raw
    assert (
        await mongo_uow.raw_records.add(
            replace(raw, ingested_at=datetime(2026, 4, 2, tzinfo=timezone.utc))
        )
        == raw
    )
    assert await mongo_uow.raw_records.get(raw.id) == raw
    assert await mongo_uow.transactions.get(transaction.id) == transaction
    assert (
        await mongo_uow.transactions.list(
            bank_transaction_id=transaction.bank_transaction_id,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )
    ) == (transaction,)
    with pytest.raises(ImmutableRecordError):
        await mongo_uow.raw_records.add(_raw("11.00"))


async def test_concurrent_versions_and_outbox_claim_are_atomic(mongo_uow):
    decisions = await asyncio.gather(
        *(mongo_uow.classifications.append(_decision(f"decision-{index}")) for index in range(12))
    )
    assert sorted(item.version for item in decisions) == list(range(1, 13))
    assert (await mongo_uow.classifications.latest("tx-1")).version == 12

    first = await mongo_uow.outbox.add(_outbox())
    assert await mongo_uow.outbox.add(_outbox("other-id")) == first
    claims = await asyncio.gather(
        *(mongo_uow.outbox.claim_pending(limit=1) for _ in range(8))
    )
    claimed = [item for batch in claims for item in batch]
    assert [item.id for item in claimed] == ["outbox-1"]
    assert claimed[0].attempt_count == 1
    completed = await mongo_uow.outbox.transition(
        "outbox-1", OutboxStatus.SUCCEEDED, qbo_entity_id="local-test-only"
    )
    assert completed.status is OutboxStatus.SUCCEEDED


async def test_oauth_state_is_hashed_expiring_and_single_use(mongo_uow):
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    saved = await mongo_uow.oauth_states.put(
        "opaque-local-test-state", expires_at=now.replace(hour=1)
    )

    assert saved.state_hash != "opaque-local-test-state"
    winners = await asyncio.gather(
        *(mongo_uow.oauth_states.consume("opaque-local-test-state", now=now) for _ in range(6))
    )
    assert sum(item is not None for item in winners) == 1

    await mongo_uow.oauth_states.put("expired-test-state", expires_at=now)
    with pytest.raises(OAuthStateExpiredError):
        await mongo_uow.oauth_states.consume(
            "expired-test-state", now=now.replace(hour=2)
        )


async def test_audit_sequence_is_atomic_and_ordered(mongo_uow):
    events = await asyncio.gather(
        *(
            mongo_uow.audit.append(
                AuditEvent(
                    "test.event",
                    {"index": index},
                    datetime(2026, 4, 1, tzinfo=timezone.utc),
                )
            )
            for index in range(10)
        )
    )
    assert sorted(event.sequence for event in events) == list(range(1, 11))
    assert [event.sequence for event in await mongo_uow.audit.list()] == list(range(1, 11))
