"""End-to-end API workflow backed only by the in-memory unit of work."""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.memory import InMemoryUnitOfWork
from app.services.ledger_bridge import LedgerBridgeService


DATASET_PATH = Path(__file__).resolve().parents[3] / (
    "Finz Accounting Data Engineering Challenge Dataset.xlsx"
)
BRIGHTFIX_MAPPING = {
    "sheet_name": "Raw Bank Transactions",
    "header_row": 4,
    "columns": {
        "transaction_id": "Bank Transaction ID",
        "transaction_date": "Transaction Date",
        "posted_date": "Posted Date",
        "description": "Description",
        "amount": "Amount (USD)",
        "currency": "Currency",
        "bank_account": "Bank Account",
    },
    "source_file_column": "Source File",
}


def test_ready_upload_and_process_challenge_workbook() -> None:
    """Removing API wiring, upload retention, or pipeline orchestration must fail."""
    service = LedgerBridgeService(InMemoryUnitOfWork())
    client = TestClient(create_app(ledger_bridge=service))

    assert client.get("/ready").json() == {"status": "ready"}

    with DATASET_PATH.open("rb") as dataset:
        upload = client.post(
            "/api/v1/uploads",
            files={
                "file": (
                    DATASET_PATH.name,
                    dataset,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert upload.status_code == 201
    upload_id = upload.json()["id"]

    processed = client.post(
        f"/api/v1/uploads/{upload_id}/process",
        json=BRIGHTFIX_MAPPING,
    )

    assert processed.status_code == 200
    assert processed.json()["counts"] == {
        "raw": 200,
        "unique": 195,
        "duplicates": 5,
        "transfer_pairs": 6,
        "classified": 195,
    }
    repeated = client.post(
        f"/api/v1/uploads/{upload_id}/process",
        json=BRIGHTFIX_MAPPING,
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "invalid_state"

    page = client.get(
        "/api/v1/transactions",
        params={"month": "2026-04", "limit": 10, "offset": 0},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 65
    assert len(page.json()["items"]) == 10
    assert all(item["transaction_date"].startswith("2026-04") for item in page.json()["items"])

    approved_revenue = client.get(
        "/api/v1/transactions",
        params={"approval": "approved", "account": "4000", "limit": 1},
    ).json()["items"][0]
    invalid_correction = client.post(
        f"/api/v1/transactions/{approved_revenue['id']}/correct",
        json={
            "account_number": "6000",
            "transaction_type": "revenue",
            "explanation": "Deliberately inconsistent test correction.",
        },
    )
    assert invalid_correction.status_code == 422
    assert invalid_correction.json()["error"]["code"] == "invalid_upload"

    suggested = client.get(
        "/api/v1/transactions",
        params={"approval": "suggested", "limit": 200},
    ).json()["items"]
    refunds = [item for item in suggested if item["classification"]["transaction_type"] == "refund"]
    assert len(refunds) == 3
    for refund in refunds:
        approved = client.post(f"/api/v1/transactions/{refund['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["approval_status"] == "approved"
        assert approved.json()["version"] == 2

    all_transactions = client.get(
        "/api/v1/transactions", params={"limit": 250}
    ).json()["items"]
    transfer_legs = [
        item
        for item in all_transactions
        if item["classification"]["transaction_type"] == "transfer"
    ]
    assert len(transfer_legs) == 12
    for transfer in transfer_legs:
        assert client.post(
            f"/api/v1/transactions/{transfer['id']}/approve"
        ).status_code == 200
    transfer_sync = client.post(
        "/api/v1/integrations/qbo/sync",
        json={
            "realm_id": "sandbox-realm",
            "transaction_ids": [item["id"] for item in transfer_legs],
        },
    )
    assert transfer_sync.status_code == 202
    assert transfer_sync.json()["planned_items"] == 6
    assert transfer_sync.json()["execution_authorized"] is False

    history = client.get(
        f"/api/v1/transactions/{refunds[0]['id']}/lineage"
    ).json()["classification_history"]
    assert [decision["version"] for decision in history] == [1, 2]

    pnl = client.get(
        "/api/v1/reports/pnl",
        params={"start_date": "2026-04-01", "end_date": "2026-06-30"},
    )
    assert pnl.status_code == 200
    assert pnl.json()["totals"] == {
        "revenue_minor": 30027500,
        "cogs_minor": 9385000,
        "gross_profit_minor": 20642500,
        "operating_expenses_minor": 13824500,
        "net_profit_minor": 6818000,
    }

    sync = client.post(
        "/api/v1/integrations/qbo/sync",
        json={"realm_id": "sandbox-realm", "transaction_ids": [refunds[0]["id"]]},
    )
    assert sync.status_code == 202
    assert sync.json()["execution_authorized"] is False
    assert sync.json()["planned_items"] == 1
    sync_status = client.get(
        f"/api/v1/integrations/qbo/sync-runs/{sync.json()['id']}"
    )
    assert sync_status.json()["status"] == "planned"
    retry = client.post(
        f"/api/v1/integrations/qbo/sync-items/{sync.json()['item_ids'][0]}/retry"
    )
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "invalid_state"

    reconciliation = client.post(
        "/api/v1/reconciliations",
        json={
            "start_date": "2026-04-01",
            "end_date": "2026-06-30",
            "qbo_report": {
                "Header": {
                    "ReportBasis": "Cash",
                    "StartPeriod": "2026-04-01",
                    "EndPeriod": "2026-06-30",
                    "Currency": "USD",
                },
                "Rows": {
                    "Row": [
                        {"ColData": [{"value": number}, {"value": f"{amount / 100:.2f}"}]}
                        for number, amount in pnl.json()["account_totals"].items()
                    ]
                    + [
                        {
                            "ColData": [
                                {"value": "Net Profit"},
                                {"value": "68180.00"},
                            ]
                        }
                    ]
                }
            },
        },
    )
    assert reconciliation.status_code == 201
    assert reconciliation.json()["status"] == "matched"
    assert all(line["difference_minor"] == 0 for line in reconciliation.json()["lines"])

    audit_events = asyncio.run(service.unit_of_work.audit.list())
    event_types = {event.event_type for event in audit_events}
    assert {
        "upload.created",
        "upload.processed",
        "classification.approved",
        "qbo.sync_planned",
        "reconciliation.completed",
    } <= event_types
