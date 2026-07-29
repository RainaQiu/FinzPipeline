"""Local-payload, zero-tolerance reconciliation endpoints."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_ledger_bridge
from app.services.ledger_bridge import LedgerBridgeService


router = APIRouter(prefix="/api/v1/reconciliations", tags=["reconciliations"])


class ReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    qbo_report: dict[str, Any]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_reconciliation(
    request: ReconciliationRequest,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.reconcile_local(
        start_date=request.start_date,
        end_date=request.end_date,
        qbo_report=request.qbo_report,
    )


@router.get("/{run_id}")
async def get_reconciliation(
    run_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return service.get_reconciliation(run_id)


@router.get("/{run_id}/differences")
async def get_differences(
    run_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    run = service.get_reconciliation(run_id)
    return {
        "id": run_id,
        "items": [
            line for line in run["lines"] if line["difference_minor"] != 0
        ],
    }
