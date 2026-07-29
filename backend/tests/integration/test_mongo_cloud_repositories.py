"""Real MongoDB contracts for the public-cloud orchestration repositories."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import pytest
from pymongo import AsyncMongoClient

from app.domain.accounting import OutboxItem, OutboxStatus
from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.demo import (
    DemoGrant,
    ExecutionLease,
    PipelineContext,
    QboConnection,
    ReconciliationRunRecord,
    ResetRun,
    SyncRunRecord,
    UploadRecord,
)
from app.domain.transactions import Direction, NormalizedTransaction, RawRecord
from app.repositories.mongo import MongoUnitOfWork
from app.repositories.protocols import AuditEvent


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("FINZ_RUN_MONGO_INTEGRATION") != "1",
        reason="set FINZ_RUN_MONGO_INTEGRATION=1 to use real local MongoDB",
    ),
]


@pytest.fixture
async def mongo_uow():
    database_name = "finz_ledger_bridge_test"
    client = AsyncMongoClient(
        os.environ["FINZ_MONGODB_URI"],
        serverSelectionTimeoutMS=5_000,
    )
    uow = MongoUnitOfWork(client, database_name)
    try:
        await client.drop_database(database_name)
        await uow.create_indexes()
        yield uow
    finally:
        assert database_name == "finz_ledger_bridge_test"
        await client.drop_database(database_name)
        await client.close()


def _upload(upload_id: str = "finz-test-upload") -> UploadRecord:
    return UploadRecord(
        id=upload_id,
        original_filename="finz-test.csv",
        media_type="text/csv",
        sha256="a" * 64,
        data=b"amount\n100\n",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def _connection() -> QboConnection:
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    return QboConnection(
        realm_id="finz-test-realm",
        company_name="Finz Test Company",
        encrypted_access_token="finz-test-access",
        encrypted_refresh_token="finz-test-refresh",
        access_expires_at=now + timedelta(hours=1),
        refresh_expires_at=now + timedelta(days=1),
        updated_at=now,
    )


def _future_non_millisecond_time() -> datetime:
    return datetime(
        2036,
        4,
        1,
        12,
        34,
        56,
        123456,
        tzinfo=timezone(timedelta(hours=8)),
    )


async def test_cloud_repository_indexes_enforce_expiry_and_uniqueness(mongo_uow):
    indexes = await mongo_uow.index_information()

    assert indexes["demo_grants"]["expires_at_ttl"]["expireAfterSeconds"] == 0
    assert indexes["execution_leases"]["expires_at_ttl"]["expireAfterSeconds"] == 0
    assert indexes["oauth_states"]["expires_at_ttl"]["expireAfterSeconds"] == 0
    assert indexes["uploads"]["id_unique"]["unique"] is True
    assert indexes["sync_runs"]["id_unique"]["unique"] is True
    assert indexes["reconciliation_runs"]["id_unique"]["unique"] is True
    assert indexes["qbo_connections"]["singleton_unique"]["unique"] is True
    assert indexes["outbox"]["idempotency_key_unique"]["unique"] is True


async def test_concurrent_execution_lease_acquisition_has_one_winner(mongo_uow):
    now = _future_non_millisecond_time()
    leases = tuple(
        ExecutionLease(
            id=f"finz-test-lease-{index}",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        for index in range(8)
    )

    acquired = await asyncio.gather(
        *(mongo_uow.execution_leases.acquire(lease, now=now) for lease in leases)
    )

    assert acquired.count(True) == 1
    replacement = ExecutionLease(
        id="finz-test-lease-replacement",
        acquired_at=now + timedelta(minutes=6),
        expires_at=now + timedelta(minutes=11),
    )
    assert await mongo_uow.execution_leases.acquire(
        replacement, now=now + timedelta(minutes=6)
    )
    await mongo_uow.execution_leases.release(replacement.id)
    assert await mongo_uow.execution_leases.acquire(
        replacement, now=now + timedelta(minutes=6)
    )


async def test_invalid_candidate_execution_leases_never_acquire(mongo_uow):
    now = _future_non_millisecond_time()
    stale_candidates = tuple(
        ExecutionLease(
            id=f"finz-test-stale-lease-{index}",
            acquired_at=now - timedelta(minutes=2),
            expires_at=now - timedelta(minutes=1),
        )
        for index in range(8)
    )

    stale_results = await asyncio.gather(
        *(
            mongo_uow.execution_leases.acquire(candidate, now=now)
            for candidate in stale_candidates
        )
    )
    future_candidate = ExecutionLease(
        id="finz-test-future-lease",
        acquired_at=now + timedelta(minutes=1),
        expires_at=now + timedelta(minutes=2),
    )

    assert stale_results == [False] * 8
    assert (
        await mongo_uow.execution_leases.acquire(future_candidate, now=now)
        is False
    )


async def test_demo_grant_consumption_is_atomic_and_single_use(mongo_uow):
    now = _future_non_millisecond_time()
    grant = DemoGrant(
        token_hash="finz-test-grant",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    await mongo_uow.demo_grants.issue(grant)

    consumed = await asyncio.gather(
        *(mongo_uow.demo_grants.consume_valid(grant.token_hash, now=now) for _ in range(8))
    )

    assert consumed.count(grant) == 1
    assert sum(item is not None for item in consumed) == 1
    assert await mongo_uow.demo_grants.consume_valid(grant.token_hash, now=now) is None


async def test_upload_bytes_round_trip_and_orchestration_records_persist(mongo_uow):
    source_time = datetime(
        2026,
        4,
        1,
        12,
        34,
        56,
        123456,
        tzinfo=timezone(timedelta(hours=8)),
    )
    canonical_time = datetime(
        2026, 4, 1, 4, 34, 56, 123000, tzinfo=timezone.utc
    )
    source = bytearray(b"amount\n100\n")
    upload = UploadRecord(
        id="finz-test-upload-round-trip",
        original_filename="finz-test.csv",
        media_type="text/csv",
        sha256="a" * 64,
        data=bytes(source),
        created_at=source_time,
        completed_at=source_time,
    )
    context = PipelineContext(
        id="finz-test-context",
        upload_id=upload.id,
        status="ready",
        transaction_statuses={"finz-test-transaction": "ready"},
        transfer_pairs={},
        created_at=source_time,
        updated_at=source_time,
    )
    sync_run = SyncRunRecord(
        id="finz-test-sync",
        status="complete",
        item_views={"finz-test-item": "complete"},
        started_at=source_time,
        completed_at=source_time,
    )
    reconciliation_run = ReconciliationRunRecord(
        id="finz-test-reconciliation",
        status="complete",
        account_views={"finz-test-account": "matched"},
        created_at=source_time,
    )
    connection = QboConnection(
        realm_id="finz-test-realm-round-trip",
        company_name="Finz Test Company",
        encrypted_access_token="finz-test-access",
        encrypted_refresh_token="finz-test-refresh",
        access_expires_at=source_time,
        refresh_expires_at=source_time,
        updated_at=source_time,
    )

    assert upload.created_at == canonical_time
    assert context.created_at == canonical_time
    assert sync_run.started_at == canonical_time
    assert reconciliation_run.created_at == canonical_time
    assert connection.updated_at == canonical_time
    assert await mongo_uow.uploads.add(upload) == upload
    assert await mongo_uow.uploads.add(upload) == upload
    assert await mongo_uow.pipeline_contexts.upsert(context) == context
    assert await mongo_uow.pipeline_contexts.upsert(context) == context
    assert await mongo_uow.sync_runs.add(sync_run) == sync_run
    assert await mongo_uow.sync_runs.add(sync_run) == sync_run
    assert (
        await mongo_uow.reconciliation_runs.add(reconciliation_run)
        == reconciliation_run
    )
    assert (
        await mongo_uow.reconciliation_runs.add(reconciliation_run)
        == reconciliation_run
    )
    assert await mongo_uow.qbo_connection.upsert(connection) == connection
    assert await mongo_uow.qbo_connection.upsert(connection) == connection
    source[:] = b"mutated data"

    loaded = await mongo_uow.uploads.get(upload.id)
    assert loaded == upload
    assert loaded is not None
    assert loaded.data == b"amount\n100\n"
    assert isinstance(loaded.data, bytes)
    assert await mongo_uow.pipeline_contexts.get(upload.id) == context
    assert await mongo_uow.sync_runs.get(sync_run.id) == sync_run
    assert (
        await mongo_uow.reconciliation_runs.get(reconciliation_run.id)
        == reconciliation_run
    )
    assert await mongo_uow.qbo_connection.get() == connection


async def test_scoped_reset_clears_demo_records_but_keeps_qbo_connection(mongo_uow):
    now = _future_non_millisecond_time()
    upload = _upload("finz-test-upload-reset")
    connection = _connection()
    await mongo_uow.uploads.add(upload)
    raw = RawRecord(
        id="finz-test-raw-reset",
        source_filename="finz-test.csv",
        source_file_sha256="b" * 64,
        source_sheet="CSV",
        source_row_number=2,
        raw_values={"finz-test": "reset"},
        raw_row_sha256="c" * 64,
        ingested_at=now,
    )
    transaction = NormalizedTransaction(
        id="finz-test-transaction-reset",
        raw_record_id=raw.id,
        bank_transaction_id="finz-test-bank-transaction-reset",
        transaction_date=date(2026, 4, 1),
        posted_date=date(2026, 4, 2),
        description_original="Finz test",
        description_normalized="finz test",
        amount_minor=-100,
        currency="USD",
        direction=Direction.OUTFLOW,
        bank_account_number="1000",
    )
    decision = ClassificationDecision(
        id="finz-test-decision-reset",
        transaction_id=transaction.id,
        account_number="6000",
        transaction_type=TransactionType.OPERATING_EXPENSE,
        source=DecisionSource.HARD_RULE,
        confidence_basis_points=10000,
        approval_status=ApprovalStatus.APPROVED,
        needs_review=False,
        explanation="Finz test.",
        created_at=now,
    )
    outbox = OutboxItem(
        id="finz-test-outbox-reset",
        realm_id="finz-test-realm",
        transaction_id=transaction.id,
        classification_decision_id=decision.id,
        classification_version=1,
        idempotency_key="finz-test-outbox-reset-key",
        payload_kind="Purchase",
        payload={"finz-test": "reset"},
        status=OutboxStatus.PENDING,
        created_at=now,
    )
    context = PipelineContext(
        id="finz-test-context-reset",
        upload_id=upload.id,
        status="ready",
        transaction_statuses={transaction.id: "ready"},
        transfer_pairs={},
        created_at=now,
        updated_at=now,
    )
    sync_run = SyncRunRecord(
        id="finz-test-sync-reset",
        status="complete",
        item_views={"finz-test-item": "complete"},
        started_at=now,
        completed_at=now,
    )
    reconciliation_run = ReconciliationRunRecord(
        id="finz-test-reconciliation-reset",
        status="complete",
        account_views={"finz-test-account": "matched"},
        created_at=now,
    )
    grant = DemoGrant(
        token_hash="finz-test-grant-reset",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    lease = ExecutionLease(
        id="finz-test-lease-reset",
        acquired_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    reset = ResetRun(
        id="finz-test-reset",
        status="running",
        started_at=now,
    )

    await mongo_uow.raw_records.add(raw)
    await mongo_uow.transactions.add(transaction)
    await mongo_uow.classifications.append(decision)
    await mongo_uow.outbox.add(outbox)
    await mongo_uow.oauth_states.put(
        "finz-test-oauth-reset", expires_at=now + timedelta(minutes=5)
    )
    await mongo_uow.audit.append(AuditEvent("finz-test-event", {}, now))
    await mongo_uow.pipeline_contexts.upsert(context)
    await mongo_uow.sync_runs.add(sync_run)
    await mongo_uow.reconciliation_runs.add(reconciliation_run)
    await mongo_uow.demo_grants.issue(grant)
    assert await mongo_uow.execution_leases.acquire(lease, now=now)
    await mongo_uow.qbo_connection.upsert(connection)
    assert await mongo_uow.demo_reset.add(reset) == reset
    assert await mongo_uow.demo_reset.add(reset) == reset

    await mongo_uow.demo_reset.clear_shared_workspace()

    assert await mongo_uow.uploads.get(upload.id) is None
    assert await mongo_uow.raw_records.get(raw.id) is None
    assert await mongo_uow.transactions.get(transaction.id) is None
    assert await mongo_uow.classifications.latest(transaction.id) is None
    assert await mongo_uow.outbox.get(outbox.id) is None
    assert (
        await mongo_uow.oauth_states.consume("finz-test-oauth-reset", now=now)
        is None
    )
    assert await mongo_uow.audit.list() == ()
    assert await mongo_uow.pipeline_contexts.get(upload.id) is None
    assert await mongo_uow.sync_runs.get(sync_run.id) is None
    assert await mongo_uow.reconciliation_runs.get(reconciliation_run.id) is None
    assert (
        await mongo_uow.demo_grants.consume_valid(grant.token_hash, now=now)
        is None
    )
    assert await mongo_uow._database["reset_runs"].count_documents({}) == 0
    after_reset_lease = ExecutionLease(
        id="finz-test-lease-after-reset",
        acquired_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    assert await mongo_uow.execution_leases.acquire(after_reset_lease, now=now)
    first_event = await mongo_uow.audit.append(
        AuditEvent("finz-test-event-after-reset", {}, now)
    )
    assert first_event.sequence == 1
    assert await mongo_uow.qbo_connection.get() == connection
