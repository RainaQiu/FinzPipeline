"""Local-payload, zero-tolerance reconciliation endpoints."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_ledger_bridge
from app.services.ledger_bridge import LedgerBridgeService


router = APIRouter(prefix="/api/v1/reconciliations", tags=["reconciliations"])


class ReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    qbo_report: dict[str, Any]


class QboReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date


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


@router.post("/qbo", status_code=status.HTTP_201_CREATED)
async def create_qbo_reconciliation(
    payload: QboReconciliationRequest,
    request: Request,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    runtime = request.app.state.qbo_runtime
    if runtime is None:
        raise HTTPException(503, "QBO Sandbox read integration is unavailable")
    try:
        report = await runtime.profit_and_loss(payload.start_date, payload.end_date)
        result = await service.reconcile_local(
            start_date=payload.start_date,
            end_date=payload.end_date,
            qbo_report=report,
        )
        result["source"] = "qbo_sandbox"
        result["no_report_data"] = bool(
            report.get("Header", {}).get("NoReportData") is True
        )
        return result
    except Exception:
        raise HTTPException(502, "QBO reconciliation failed") from None


@router.get("/{run_id}")
async def get_reconciliation(
    run_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.get_reconciliation(run_id)


@router.get("/{run_id}/differences")
async def get_differences(
    run_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    run = await service.get_reconciliation(run_id)
    return {
        "id": run_id,
        "items": [
            line for line in run["lines"] if line["difference_minor"] != 0
        ],
    }
