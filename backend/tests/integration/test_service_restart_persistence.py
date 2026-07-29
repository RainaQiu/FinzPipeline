"""Service reconstruction must not lose API-facing ledger workflow state."""

from __future__ import annotations

from datetime import date

import pytest

from app.repositories.memory import InMemoryUnitOfWork
from app.services.ingestion import IngestionError
from app.services.ledger_bridge import LedgerBridgeService
from tests.fixtures.golden_dataset import (
    BRIGHTFIX_MAPPING,
    DATASET_NAME,
    dataset_bytes,
)


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
