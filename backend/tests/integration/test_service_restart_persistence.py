"""Service reconstruction must not lose API-facing ledger workflow state."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from app.repositories.memory import InMemoryUnitOfWork
from app.services.ingestion import IngestionError
from app.services.ledger_bridge import (
    InvalidStateError,
    LedgerBridgeService,
    ResourceNotFoundError,
)
from tests.fixtures.golden_dataset import (
    BRIGHTFIX_MAPPING,
    DATASET_NAME,
    dataset_bytes,
)

EXPECTED_PROCESSING_CLAIM_TIMEOUT = timedelta(minutes=5)


class _FailOnceClassificationRepository:
    def __init__(self, delegate, *, fail_on_call: int) -> None:
        self._delegate = delegate
        self._fail_on_call = fail_on_call
        self._calls = 0
        self._failed = False

    async def append(self, decision):
        self._calls += 1
        if not self._failed and self._calls == self._fail_on_call:
            self._failed = True
            raise RuntimeError("classification write failed")
        return await self._delegate.append(decision)

    async def latest(self, transaction_id):
        return await self._delegate.latest(transaction_id)

    async def history(self, transaction_id, *, offset=0, limit=None):
        return await self._delegate.history(
            transaction_id, offset=offset, limit=limit
        )


class _FailOnceTerminalUploadRepository:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self._failed = False

    async def add(self, upload):
        return await self._delegate.add(upload)

    async def get(self, upload_id):
        return await self._delegate.get(upload_id)

    async def transition_status(
        self, upload, *, expected_status, expected_token=None
    ):
        if not self._failed and upload.status == "completed":
            self._failed = True
            raise RuntimeError("terminal publish failed")
        return await self._delegate.transition_status(
            upload,
            expected_status=expected_status,
            expected_token=expected_token,
        )


class _BarrierUploadRepository:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self._uploaded_reads = 0
        self._both_read = asyncio.Event()

    async def add(self, upload):
        return await self._delegate.add(upload)

    async def get(self, upload_id):
        upload = await self._delegate.get(upload_id)
        if upload is not None and upload.status == "uploaded":
            self._uploaded_reads += 1
            if self._uploaded_reads == 2:
                self._both_read.set()
            await self._both_read.wait()
        return upload

    async def transition_status(
        self, upload, *, expected_status, expected_token=None
    ):
        return await self._delegate.transition_status(
            upload,
            expected_status=expected_status,
            expected_token=expected_token,
        )


class _FailingAuditRepository:
    def __init__(self, delegate, *event_types: str) -> None:
        self._delegate = delegate
        self._event_types = frozenset(event_types)

    async def append(self, event):
        if event.event_type in self._event_types:
            raise RuntimeError(f"{event.event_type} audit failed")
        return await self._delegate.append(event)

    async def list(self, *, offset=0, limit=None):
        return await self._delegate.list(offset=offset, limit=limit)


class _BlockingClassificationRepository:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self._blocked = False

    async def append(self, decision):
        if not self._blocked:
            self._blocked = True
            self.entered.set()
            await self.release.wait()
        return await self._delegate.append(decision)

    async def latest(self, transaction_id):
        return await self._delegate.latest(transaction_id)

    async def history(self, transaction_id, *, offset=0, limit=None):
        return await self._delegate.history(
            transaction_id, offset=offset, limit=limit
        )


class _FirstContextWriteBarrier:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self._calls = 0

    async def upsert(self, context, *, replaces_token=None):
        self._calls += 1
        if self._calls == 1:
            self.entered.set()
            await self.release.wait()
            context = replace(
                context,
                transaction_statuses={
                    transaction_id: {"duplicate_status": "stale-worker"}
                    for transaction_id in context.transaction_statuses
                },
                transfer_pairs={},
                counts={"raw": 999},
            )
        return await self._delegate.upsert(
            context,
            replaces_token=replaces_token,
        )

    async def get(self, upload_id):
        return await self._delegate.get(upload_id)

    async def get_for_transaction(self, transaction_id):
        return await self._delegate.get_for_transaction(transaction_id)


async def _create_challenge_upload(service: LedgerBridgeService):
    return await service.create_upload(
        filename=DATASET_NAME,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        data=dataset_bytes(),
    )


async def _assert_partial_pipeline_is_not_published(
    service: LedgerBridgeService, uow: InMemoryUnitOfWork
) -> None:
    stored_transactions = await uow.transactions.list()
    assert stored_transactions
    transaction_id = stored_transactions[0].id

    assert (await service.list_transactions(limit=250))["total"] == 0
    with pytest.raises(ResourceNotFoundError):
        await service.get_transaction(transaction_id)
    with pytest.raises(ResourceNotFoundError):
        await service.get_lineage(transaction_id)
    with pytest.raises(ResourceNotFoundError):
        await service.approve_transaction(transaction_id)
    pnl = await service.pnl(date(2026, 4, 1), date(2026, 6, 30))
    assert pnl["totals"] == {
        "revenue_minor": 0,
        "cogs_minor": 0,
        "gross_profit_minor": 0,
        "operating_expenses_minor": 0,
        "net_profit_minor": 0,
    }
    with pytest.raises(ResourceNotFoundError):
        await service.plan_qbo_sync(
            realm_id="sandbox-realm",
            transaction_ids=[transaction_id],
        )


def _matching_qbo_report(pnl):
    return {
        "Header": {
            "ReportName": "ProfitAndLoss",
            "ReportBasis": "Cash",
            "StartPeriod": "2026-04-01",
            "EndPeriod": "2026-06-30",
            "Currency": "USD",
        },
        "Rows": {
            "Row": [
                {
                    "ColData": [
                        {"value": account_number},
                        {"value": f"{amount_minor / 100:.2f}"},
                    ]
                }
                for account_number, amount_minor in pnl["account_totals"].items()
            ]
            + [
                {
                    "ColData": [
                        {"value": "Net Profit"},
                        {"value": f"{pnl['totals']['net_profit_minor'] / 100:.2f}"},
                    ]
                }
            ]
        },
    }


@pytest.mark.asyncio
async def test_processed_workflow_views_survive_service_reconstruction():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    source = dataset_bytes()
    created = await service.create_upload(
        filename=DATASET_NAME,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        data=source,
    )
    processed = await service.process_upload(created["id"], BRIGHTFIX_MAPPING)
    upload_before = await service.get_upload(created["id"])
    transactions_before = await service.list_transactions(limit=250)
    duplicate_before = next(
        item
        for item in transactions_before["items"]
        if item["duplicate_status"] != "unique"
    )
    transfer_legs = [
        item
        for item in transactions_before["items"]
        if item["classification"]["transaction_type"] == "transfer"
    ]
    for transfer in transfer_legs:
        await service.approve_transaction(transfer["id"])
    approved_transfer_before = await service.get_transaction(transfer_legs[0]["id"])
    lineage_before = await service.get_lineage(transfer_legs[0]["id"])

    del service
    restarted = LedgerBridgeService(uow)

    assert await restarted.get_upload(created["id"]) == upload_before
    assert upload_before["status"] == "completed"
    assert upload_before["counts"] == processed["counts"]
    assert upload_before["size_bytes"] == len(source)
    assert await restarted.get_transaction(duplicate_before["id"]) == duplicate_before
    assert (
        await restarted.get_transaction(approved_transfer_before["id"])
        == approved_transfer_before
    )
    assert await restarted.get_lineage(transfer_legs[0]["id"]) == lineage_before
    assert lineage_before["transfer_pair_id"] is not None

    sync = await restarted.plan_qbo_sync(
        realm_id="sandbox-realm",
        transaction_ids=[item["id"] for item in transfer_legs],
    )
    assert sync["planned_items"] == 6

    del restarted
    restarted_again = LedgerBridgeService(uow)
    assert await restarted_again.get_sync_run(sync["id"]) == sync

    pnl = await restarted_again.pnl(date(2026, 4, 1), date(2026, 6, 30))
    reconciliation = await restarted_again.reconcile_local(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
        qbo_report={
            "Header": {
                "ReportName": "ProfitAndLoss",
                "ReportBasis": "Cash",
                "StartPeriod": "2026-04-01",
                "EndPeriod": "2026-06-30",
                "Currency": "USD",
            },
            "Rows": {
                "Row": [
                    {
                        "ColData": [
                            {"value": account_number},
                            {"value": f"{amount_minor / 100:.2f}"},
                        ]
                    }
                    for account_number, amount_minor in pnl["account_totals"].items()
                ]
                + [
                    {
                        "ColData": [
                            {"value": "Net Profit"},
                            {"value": f"{pnl['totals']['net_profit_minor'] / 100:.2f}"},
                        ]
                    }
                ]
            },
        },
    )

    del restarted_again
    final_service = LedgerBridgeService(uow)
    assert (
        await final_service.get_reconciliation(reconciliation["id"])
        == reconciliation
    )


@pytest.mark.asyncio
async def test_failed_processing_status_survives_service_reconstruction():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    upload = await service.create_upload(
        filename="invalid.csv",
        media_type="text/csv",
        data=b"unexpected\nvalue\n",
    )

    with pytest.raises(IngestionError):
        await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)

    persisted = await uow.uploads.get(upload["id"])
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.error_summary == ("IngestionError",)

    restarted = LedgerBridgeService(uow)
    failed_view = await restarted.get_upload(upload["id"])
    assert failed_view["status"] == "failed"
    assert "counts" not in failed_view


@pytest.mark.asyncio
async def test_mid_classification_failure_is_hidden_and_retry_is_idempotent():
    uow = InMemoryUnitOfWork()
    uow.classifications = _FailOnceClassificationRepository(
        uow.classifications, fail_on_call=3
    )
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)

    with pytest.raises(RuntimeError, match="classification write failed"):
        await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)

    assert (await service.get_upload(upload["id"]))["status"] == "failed"
    await _assert_partial_pipeline_is_not_published(service, uow)

    retried = await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)
    assert retried["status"] == "completed"
    assert retried["counts"]["classified"] == 195
    assert (await service.list_transactions(limit=250))["total"] == 195


@pytest.mark.asyncio
async def test_context_before_terminal_publish_is_hidden_and_retry_completes():
    uow = InMemoryUnitOfWork()
    uow.uploads = _FailOnceTerminalUploadRepository(uow.uploads)
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)

    with pytest.raises(RuntimeError, match="terminal publish failed"):
        await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)

    stored_context = await uow.pipeline_contexts.get(upload["id"])
    assert stored_context is not None
    assert stored_context.status == "completed"
    await _assert_partial_pipeline_is_not_published(service, uow)

    retried = await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)
    assert retried["status"] == "completed"
    assert (await service.list_transactions(limit=250))["total"] == 195


@pytest.mark.asyncio
async def test_only_one_concurrent_service_processor_can_publish():
    uow = InMemoryUnitOfWork()
    uow.uploads = _BarrierUploadRepository(uow.uploads)
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)

    results = await asyncio.gather(
        *(
            service.process_upload(upload["id"], BRIGHTFIX_MAPPING)
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, InvalidStateError) for result in results) == 1
    assert (await service.get_upload(upload["id"]))["status"] == "completed"
    processed_events = [
        event
        for event in await uow.audit.list()
        if event.event_type == "upload.processed"
    ]
    assert len(processed_events) == 1


@pytest.mark.asyncio
async def test_published_upload_is_returned_when_processed_audit_fails():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)
    uow.audit = _FailingAuditRepository(uow.audit, "upload.processed")

    processed = await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)

    assert processed["status"] == "completed"
    assert (await service.get_upload(upload["id"]))["status"] == "completed"
    assert (await service.list_transactions(limit=250))["total"] == 195


@pytest.mark.asyncio
async def test_created_upload_is_returned_when_audit_fails():
    uow = InMemoryUnitOfWork()
    uow.audit = _FailingAuditRepository(uow.audit, "upload.created")
    service = LedgerBridgeService(uow)

    upload = await _create_challenge_upload(service)

    assert upload["status"] == "uploaded"
    assert await uow.uploads.get(upload["id"]) is not None


@pytest.mark.asyncio
async def test_sync_run_is_returned_when_audit_fails():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)
    await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)
    suggested = await service.list_transactions(
        approval="suggested", limit=250
    )
    transaction = next(
        item
        for item in suggested["items"]
        if item["classification"]["transaction_type"] == "refund"
    )
    await service.approve_transaction(transaction["id"])
    uow.audit = _FailingAuditRepository(uow.audit, "qbo.sync_planned")

    sync = await service.plan_qbo_sync(
        realm_id="sandbox-realm",
        transaction_ids=[transaction["id"]],
    )

    assert sync["planned_items"] == 1
    assert await service.get_sync_run(sync["id"]) == sync


@pytest.mark.asyncio
async def test_reconciliation_is_returned_when_audit_fails():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)
    await service.process_upload(upload["id"], BRIGHTFIX_MAPPING)
    pnl = await service.pnl(date(2026, 4, 1), date(2026, 6, 30))
    uow.audit = _FailingAuditRepository(uow.audit, "reconciliation.completed")

    reconciliation = await service.reconcile_local(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
        qbo_report=_matching_qbo_report(pnl),
    )

    assert reconciliation["status"] == "matched"
    assert (
        await service.get_reconciliation(reconciliation["id"])
        == reconciliation
    )


@pytest.mark.asyncio
async def test_duplicate_upload_gets_clear_transaction_ownership_conflict():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    first = await _create_challenge_upload(service)
    await service.process_upload(first["id"], BRIGHTFIX_MAPPING)
    second = await _create_challenge_upload(service)

    with pytest.raises(InvalidStateError, match="another upload"):
        await service.process_upload(second["id"], BRIGHTFIX_MAPPING)

    assert (await service.get_upload(second["id"]))["status"] == "failed"
    assert (await service.list_transactions(limit=250))["total"] == 195


@pytest.mark.asyncio
async def test_completed_upload_publishes_matching_private_context_token():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    upload_view = await _create_challenge_upload(service)

    completed_view = await service.process_upload(
        upload_view["id"], BRIGHTFIX_MAPPING
    )
    upload = await uow.uploads.get(upload_view["id"])
    context = await uow.pipeline_contexts.get(upload_view["id"])

    assert upload is not None
    assert context is not None
    assert upload.published_context_token == context.claim_token
    assert context.claim_token not in repr(upload)
    assert context.claim_token not in repr(context)
    assert "published_context_token" not in completed_view
    assert "claim_token" not in completed_view
    assert "published_context_token" not in await service.get_upload(upload.id)
    assert "claim_token" not in await service.get_upload(upload.id)


@pytest.mark.asyncio
async def test_context_token_mismatch_is_hidden_from_every_published_view():
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow)
    upload_view = await _create_challenge_upload(service)
    await service.process_upload(upload_view["id"], BRIGHTFIX_MAPPING)
    context = await uow.pipeline_contexts.get(upload_view["id"])
    assert context is not None
    mismatched = replace(
        context,
        claim_token="finz-test-unpublished-context-owner",
        counts={"raw": 999},
    )
    await uow.pipeline_contexts.upsert(
        mismatched,
        replaces_token=context.claim_token,
    )

    assert "counts" not in await service.get_upload(upload_view["id"])
    assert (await service.list_transactions(limit=250))["total"] == 0
    pnl = await service.pnl(date(2026, 4, 1), date(2026, 6, 30))
    assert pnl["totals"]["revenue_minor"] == 0
    assert pnl["totals"]["net_profit_minor"] == 0
    sync = await service.plan_qbo_sync(
        realm_id="sandbox-realm",
        transaction_ids=None,
    )
    assert sync["planned_items"] == 0


@pytest.mark.asyncio
async def test_cancelled_processor_releases_claim_and_retry_completes():
    uow = InMemoryUnitOfWork()
    blocking = _BlockingClassificationRepository(uow.classifications)
    uow.classifications = blocking
    service = LedgerBridgeService(uow)
    upload = await _create_challenge_upload(service)
    task = asyncio.create_task(
        service.process_upload(upload["id"], BRIGHTFIX_MAPPING)
    )
    await blocking.entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    cancelled = await uow.uploads.get(upload["id"])
    assert cancelled is not None
    assert cancelled.status == "failed"
    assert cancelled.error_summary == ("CancelledError",)
    assert cancelled.processing_started_at is None
    assert cancelled.processing_token is None
    cancelled_view = await service.get_upload(upload["id"])
    assert "processing_started_at" not in cancelled_view
    assert "processing_token" not in cancelled_view

    restarted = LedgerBridgeService(uow)
    completed = await restarted.process_upload(
        upload["id"], BRIGHTFIX_MAPPING
    )
    assert completed["status"] == "completed"
    assert "processing_started_at" not in completed
    assert "processing_token" not in completed
    assert (await restarted.list_transactions(limit=250))["total"] == 195


@pytest.mark.asyncio
async def test_stale_processing_claim_is_reclaimed_at_timeout_boundary():
    fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow, clock=lambda: fixed_now)
    upload_view = await _create_challenge_upload(service)
    upload = await uow.uploads.get(upload_view["id"])
    assert upload is not None
    stale = replace(
        upload,
        status="processing",
        processing_started_at=(
            fixed_now - EXPECTED_PROCESSING_CLAIM_TIMEOUT
        ),
        processing_token="finz-test-crashed-worker-token",
    )
    await uow.uploads.transition_status(
        stale, expected_status="uploaded"
    )

    restarted = LedgerBridgeService(uow, clock=lambda: fixed_now)
    completed = await restarted.process_upload(
        upload.id, BRIGHTFIX_MAPPING
    )

    assert completed["status"] == "completed"
    assert (await restarted.list_transactions(limit=250))["total"] == 195


@pytest.mark.asyncio
async def test_fresh_processing_claim_remains_owned_until_timeout():
    fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    uow = InMemoryUnitOfWork()
    service = LedgerBridgeService(uow, clock=lambda: fixed_now)
    upload_view = await _create_challenge_upload(service)
    upload = await uow.uploads.get(upload_view["id"])
    assert upload is not None
    fresh = replace(
        upload,
        status="processing",
        processing_started_at=(
            fixed_now
            - EXPECTED_PROCESSING_CLAIM_TIMEOUT
            + timedelta(milliseconds=1)
        ),
        processing_token="finz-test-active-worker-token",
    )
    await uow.uploads.transition_status(
        fresh, expected_status="uploaded"
    )

    restarted = LedgerBridgeService(uow, clock=lambda: fixed_now)
    with pytest.raises(InvalidStateError, match="already being processed"):
        await restarted.process_upload(upload.id, BRIGHTFIX_MAPPING)

    assert await uow.uploads.get(upload.id) == fresh


@pytest.mark.asyncio
async def test_reclaimed_worker_cannot_overwrite_published_context_views():
    started_at = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    current_time = [started_at]
    uow = InMemoryUnitOfWork()
    barrier = _FirstContextWriteBarrier(uow.pipeline_contexts)
    uow.pipeline_contexts = barrier
    first_service = LedgerBridgeService(
        uow,
        clock=lambda: current_time[0],
    )
    upload_view = await _create_challenge_upload(first_service)
    first_task = asyncio.create_task(
        first_service.process_upload(upload_view["id"], BRIGHTFIX_MAPPING)
    )
    await barrier.entered.wait()

    current_time[0] = started_at + EXPECTED_PROCESSING_CLAIM_TIMEOUT
    reclaimed_service = LedgerBridgeService(
        uow,
        clock=lambda: current_time[0],
    )
    completed = await reclaimed_service.process_upload(
        upload_view["id"], BRIGHTFIX_MAPPING
    )
    published_upload = await uow.uploads.get(upload_view["id"])
    published_context = await uow.pipeline_contexts.get(upload_view["id"])
    assert published_upload is not None
    assert published_context is not None
    assert (
        published_upload.published_context_token
        == published_context.claim_token
    )
    assert completed["counts"] == dict(published_context.counts)

    before_upload = await reclaimed_service.get_upload(upload_view["id"])
    before_transactions = await reclaimed_service.list_transactions(limit=250)
    transfer_legs = [
        item
        for item in before_transactions["items"]
        if item["classification"]["transaction_type"] == "transfer"
    ]
    for transaction in transfer_legs:
        await reclaimed_service.approve_transaction(transaction["id"])
    before_lineage = await reclaimed_service.get_lineage(
        transfer_legs[0]["id"]
    )
    before_sync = await reclaimed_service.plan_qbo_sync(
        realm_id="sandbox-realm",
        transaction_ids=[item["id"] for item in transfer_legs],
    )
    assert before_lineage["transfer_pair_id"] is not None
    assert before_sync["planned_items"] == 6

    barrier.release.set()
    with pytest.raises(InvalidStateError):
        await first_task

    assert await uow.uploads.get(upload_view["id"]) == published_upload
    assert await uow.pipeline_contexts.get(upload_view["id"]) == published_context
    assert await reclaimed_service.get_upload(upload_view["id"]) == before_upload
    after_transactions = await reclaimed_service.list_transactions(limit=250)
    assert [
        (item["id"], item["duplicate_status"])
        for item in after_transactions["items"]
    ] == [
        (item["id"], item["duplicate_status"])
        for item in before_transactions["items"]
    ]
    assert (
        await reclaimed_service.get_lineage(transfer_legs[0]["id"])
        == before_lineage
    )
    after_sync = await reclaimed_service.plan_qbo_sync(
        realm_id="sandbox-realm",
        transaction_ids=[item["id"] for item in transfer_legs],
    )
    assert after_sync["planned_items"] == before_sync["planned_items"]
    assert after_sync["item_ids"] == before_sync["item_ids"]
