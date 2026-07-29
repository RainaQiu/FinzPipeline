"""Contract tests for the local, concurrency-safe repository implementation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

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
from app.repositories.memory import InMemoryUnitOfWork
from app.repositories.protocols import (
    AuditEvent,
    ImmutableRecordError,
    InvalidStateTransitionError,
    OAuthStateExpiredError,
)


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


@pytest.mark.asyncio
async def test_demo_grant_is_single_use_and_expires():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    valid = DemoGrant(
        token_hash="finz-test-valid-grant",
        created_at=now,
        expires_at=now.replace(hour=1),
    )
    expired = DemoGrant(
        token_hash="finz-test-expired-grant",
        created_at=now,
        expires_at=now,
    )
    await uow.demo_grants.issue(valid)
    await uow.demo_grants.issue(expired)

    winners = await asyncio.gather(
        *(uow.demo_grants.consume_valid(valid.token_hash, now=now) for _ in range(8))
    )

    assert winners.count(valid) == 1
    assert sum(item is not None for item in winners) == 1
    assert await uow.demo_grants.consume_valid(valid.token_hash, now=now) is None
    assert await uow.demo_grants.consume_valid(expired.token_hash, now=now) is None


@pytest.mark.asyncio
async def test_only_one_execution_lease_can_be_active():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    leases = tuple(
        ExecutionLease(
            id=f"finz-test-lease-{index}",
            acquired_at=now,
            expires_at=now.replace(minute=5),
        )
        for index in range(8)
    )

    acquired = await asyncio.gather(
        *(uow.execution_leases.acquire(lease, now=now) for lease in leases)
    )

    assert acquired.count(True) == 1
    replacement = ExecutionLease(
        id="finz-test-replacement-lease",
        acquired_at=now.replace(minute=6),
        expires_at=now.replace(minute=11),
    )
    assert await uow.execution_leases.acquire(
        replacement, now=now.replace(minute=6)
    )
    await uow.execution_leases.release(replacement.id)
    assert await uow.execution_leases.acquire(replacement, now=now.replace(minute=6))


@pytest.mark.asyncio
async def test_concurrent_expired_candidate_leases_are_all_rejected():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, 12, tzinfo=timezone.utc)
    candidates = tuple(
        ExecutionLease(
            id=f"finz-test-stale-lease-{index}",
            acquired_at=now - timedelta(minutes=2),
            expires_at=now - timedelta(minutes=1),
        )
        for index in range(8)
    )

    acquired = await asyncio.gather(
        *(uow.execution_leases.acquire(lease, now=now) for lease in candidates)
    )

    assert acquired == [False] * 8


@pytest.mark.asyncio
async def test_not_yet_acquired_candidate_lease_is_rejected():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, 12, tzinfo=timezone.utc)
    candidate = ExecutionLease(
        id="finz-test-future-lease",
        acquired_at=now + timedelta(minutes=1),
        expires_at=now + timedelta(minutes=2),
    )

    assert await uow.execution_leases.acquire(candidate, now=now) is False


@pytest.mark.asyncio
async def test_reset_clears_demo_records_but_keeps_configuration():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    upload = UploadRecord(
        id="finz-test-upload-reset",
        original_filename="finz-test.csv",
        media_type="text/csv",
        sha256="a" * 64,
        data=b"amount\n100\n",
        created_at=now,
    )
    context = PipelineContext(
        id="finz-test-context-reset",
        upload_id=upload.id,
        status="ready",
        transaction_statuses={"finz-test-transaction": "ready"},
        transfer_pairs={},
        created_at=now,
        updated_at=now,
    )
    sync_run = SyncRunRecord(
        id="finz-test-sync-reset",
        status="complete",
        item_views={},
        started_at=now,
        completed_at=now,
    )
    reconciliation_run = ReconciliationRunRecord(
        id="finz-test-reconciliation-reset",
        status="complete",
        account_views={},
        created_at=now,
    )
    connection = QboConnection(
        realm_id="finz-test-realm",
        company_name="Finz Test Company",
        encrypted_access_token="finz-test-access",
        encrypted_refresh_token="finz-test-refresh",
        access_expires_at=now.replace(hour=1),
        refresh_expires_at=now.replace(day=2),
        updated_at=now,
    )
    await uow.uploads.add(upload)
    await uow.pipeline_contexts.upsert(context)
    await uow.sync_runs.add(sync_run)
    await uow.reconciliation_runs.add(reconciliation_run)
    await uow.raw_records.add(_raw("finz-test-raw-reset"))
    await uow.transactions.add(
        _transaction("finz-test-transaction-reset", raw_id="finz-test-raw-reset")
    )
    await uow.classifications.append(_decision("finz-test-decision-reset"))
    await uow.outbox.add(
        _outbox("finz-test-outbox-reset", "finz-test-outbox-reset-key")
    )
    await uow.oauth_states.put(
        "finz-test-oauth-reset", expires_at=now.replace(hour=1)
    )
    await uow.audit.append(AuditEvent("finz-test-event", {}, now))
    await uow.qbo_connection.upsert(connection)
    await uow.demo_grants.issue(
        DemoGrant(
            token_hash="finz-test-reset-grant",
            created_at=now,
            expires_at=now.replace(hour=1),
        )
    )
    await uow.execution_leases.acquire(
        ExecutionLease(
            id="finz-test-reset-lease",
            acquired_at=now,
            expires_at=now.replace(hour=1),
        ),
        now=now,
    )
    await uow.demo_reset.add(
        ResetRun(id="finz-test-reset", status="running", started_at=now)
    )

    await uow.demo_reset.clear_shared_workspace()

    assert await uow.uploads.get(upload.id) is None
    assert await uow.pipeline_contexts.get(upload.id) is None
    assert await uow.sync_runs.get(sync_run.id) is None
    assert await uow.reconciliation_runs.get(reconciliation_run.id) is None
    assert await uow.raw_records.get("finz-test-raw-reset") is None
    assert await uow.transactions.get("finz-test-transaction-reset") is None
    assert await uow.classifications.latest("tx-1") is None
    assert await uow.outbox.get("finz-test-outbox-reset") is None
    assert await uow.oauth_states.consume("finz-test-oauth-reset", now=now) is None
    assert await uow.audit.list() == ()
    assert (
        await uow.demo_grants.consume_valid("finz-test-reset-grant", now=now)
        is None
    )
    assert await uow.qbo_connection.get() == connection
    assert await uow.execution_leases.acquire(
        ExecutionLease(
            id="finz-test-after-reset-lease",
            acquired_at=now,
            expires_at=now.replace(hour=1),
        ),
        now=now,
    )


@pytest.mark.asyncio
async def test_upload_bytes_round_trip_without_mutation():
    uow = InMemoryUnitOfWork()
    source = bytearray(b"amount\n100\n")
    upload = UploadRecord(
        id="finz-test-upload-bytes",
        original_filename="finz-test.csv",
        media_type="text/csv",
        sha256="b" * 64,
        data=bytes(source),
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    await uow.uploads.add(upload)
    source[:] = b"mutated data"

    loaded = await uow.uploads.get(upload.id)
    assert loaded == upload
    assert loaded is not None
    assert loaded.data == b"amount\n100\n"
    assert isinstance(loaded.data, bytes)


@pytest.mark.asyncio
async def test_upload_status_transition_is_atomic_and_preserves_source_fields():
    uow = InMemoryUnitOfWork()
    upload = UploadRecord(
        id="finz-test-upload-status",
        original_filename="finz-test.csv",
        media_type="text/csv",
        sha256="c" * 64,
        data=b"amount\n100\n",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    await uow.uploads.add(upload)
    processing = replace(upload, status="processing")
    completed = replace(
        upload,
        status="completed",
        mapping_version=1,
        row_count=1,
        completed_at=datetime(2026, 4, 1, 1, tzinfo=timezone.utc),
    )

    assert (
        await uow.uploads.transition_status(
            processing, expected_status="uploaded"
        )
        == processing
    )
    assert (
        await uow.uploads.transition_status(
            completed, expected_status="processing"
        )
        == completed
    )
    assert await uow.uploads.get(upload.id) == completed

    with pytest.raises(InvalidStateTransitionError):
        await uow.uploads.transition_status(
            replace(completed, status="processing"),
            expected_status="completed",
        )

    tampered_values = (
        {"data": b"amount\n999\n"},
        {"sha256": "d" * 64},
        {"original_filename": "other.csv"},
        {"media_type": "application/csv"},
        {"created_at": datetime(2026, 4, 2, tzinfo=timezone.utc)},
    )
    for index, changes in enumerate(tampered_values):
        candidate = replace(upload, id=f"{upload.id}-{index}")
        await uow.uploads.add(candidate)
        candidate_processing = replace(candidate, status="processing")
        await uow.uploads.transition_status(
            candidate_processing, expected_status="uploaded"
        )
        with pytest.raises(ImmutableRecordError):
            await uow.uploads.transition_status(
                replace(candidate_processing, status="completed", **changes),
                expected_status="processing",
            )


@pytest.mark.asyncio
async def test_only_one_concurrent_upload_processor_wins_compare_and_set():
    uow = InMemoryUnitOfWork()
    upload = UploadRecord(
        id="finz-test-upload-concurrent",
        original_filename="finz-test.csv",
        media_type="text/csv",
        sha256="e" * 64,
        data=b"amount\n100\n",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    await uow.uploads.add(upload)
    processing = replace(upload, status="processing")

    results = await asyncio.gather(
        *(
            uow.uploads.transition_status(
                processing, expected_status="uploaded"
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert results.count(processing) == 1
    assert sum(
        isinstance(result, InvalidStateTransitionError) for result in results
    ) == 1
    assert await uow.uploads.get(upload.id) == processing


@pytest.mark.asyncio
async def test_pipeline_context_is_retrievable_by_exact_transaction_id():
    uow = InMemoryUnitOfWork()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    context = PipelineContext(
        id="finz-test-context-transaction",
        upload_id="finz-test-upload-transaction",
        status="completed",
        transaction_statuses={
            "finz-test.transaction.$literal": {"duplicate_status": "canonical"},
            "finz-test-other-transaction": {"duplicate_status": "unique"},
        },
        transfer_pairs={},
        created_at=now,
        updated_at=now,
    )
    await uow.pipeline_contexts.upsert(context)

    assert (
        await uow.pipeline_contexts.get_for_transaction(
            "finz-test.transaction.$literal"
        )
        == context
    )
    assert (
        await uow.pipeline_contexts.get_for_transaction("finz-test-missing")
        is None
    )

    overlapping = replace(
        context,
        id="finz-test-context-overlap",
        upload_id="finz-test-upload-overlap",
        transaction_statuses={
            "finz-test.transaction.$literal": {"duplicate_status": "unique"}
        },
    )
    with pytest.raises(ValueError, match="already belongs to upload"):
        await uow.pipeline_contexts.upsert(overlapping)
    assert (
        await uow.pipeline_contexts.get_for_transaction(
            "finz-test.transaction.$literal"
        )
        == context
    )
