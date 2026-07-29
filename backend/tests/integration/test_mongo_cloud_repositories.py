"""Real MongoDB contracts for the public-cloud orchestration repositories."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from pymongo import AsyncMongoClient

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
from app.domain.transactions import RawRecord
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
    now = datetime.now(timezone.utc)
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


async def test_demo_grant_consumption_is_atomic_and_single_use(mongo_uow):
    now = datetime.now(timezone.utc)
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
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    source = bytearray(b"amount\n100\n")
    upload = _upload("finz-test-upload-round-trip")
    upload = UploadRecord(
        id=upload.id,
        original_filename=upload.original_filename,
        media_type=upload.media_type,
        sha256=upload.sha256,
        data=bytes(source),
        created_at=upload.created_at,
    )
    context = PipelineContext(
        id="finz-test-context",
        upload_id=upload.id,
        status="ready",
        transaction_statuses={"finz-test-transaction": "ready"},
        transfer_pairs={},
        created_at=now,
        updated_at=now,
    )
    sync_run = SyncRunRecord(
        id="finz-test-sync",
        status="complete",
        item_views={"finz-test-item": "complete"},
        started_at=now,
        completed_at=now,
    )
    reconciliation_run = ReconciliationRunRecord(
        id="finz-test-reconciliation",
        status="complete",
        account_views={"finz-test-account": "matched"},
        created_at=now,
    )

    await mongo_uow.uploads.add(upload)
    await mongo_uow.pipeline_contexts.upsert(context)
    await mongo_uow.sync_runs.add(sync_run)
    await mongo_uow.reconciliation_runs.add(reconciliation_run)
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


async def test_scoped_reset_clears_demo_records_but_keeps_qbo_connection(mongo_uow):
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    upload = _upload("finz-test-upload-reset")
    connection = _connection()
    await mongo_uow.uploads.add(upload)
    await mongo_uow.raw_records.add(
        RawRecord(
            id="finz-test-raw-reset",
            source_filename="finz-test.csv",
            source_file_sha256="b" * 64,
            source_sheet="CSV",
            source_row_number=2,
            raw_values={"finz-test": "reset"},
            raw_row_sha256="c" * 64,
            ingested_at=now,
        )
    )
    await mongo_uow.oauth_states.put(
        "finz-test-oauth-reset", expires_at=now + timedelta(minutes=5)
    )
    await mongo_uow.audit.append(AuditEvent("finz-test-event", {}, now))
    await mongo_uow.qbo_connection.upsert(connection)
    await mongo_uow.demo_reset.add(
        ResetRun(id="finz-test-reset", status="running", started_at=now)
    )

    await mongo_uow.demo_reset.clear_shared_workspace()

    assert await mongo_uow.uploads.get(upload.id) is None
    assert await mongo_uow.raw_records.get("finz-test-raw-reset") is None
    assert (
        await mongo_uow.oauth_states.consume("finz-test-oauth-reset", now=now)
        is None
    )
    assert await mongo_uow.audit.list() == ()
    assert await mongo_uow.qbo_connection.get() == connection
