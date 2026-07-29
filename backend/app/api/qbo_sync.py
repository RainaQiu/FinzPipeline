"""Plan-only QuickBooks synchronization endpoints."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_ledger_bridge
from app.services.ledger_bridge import InvalidStateError, LedgerBridgeService


router = APIRouter(prefix="/api/v1/integrations/qbo", tags=["QuickBooks"])


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realm_id: str = Field(min_length=1, max_length=200)
    transaction_ids: list[str] | None = Field(default=None, max_length=250)


@router.get("/status")
async def qbo_status() -> dict[str, object]:
    return {
        "mode": "plan_only",
        "execution_authorized": False,
        "transaction_write_network_accessed": False,
    }


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync(
    request: SyncRequest,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.plan_qbo_sync(
        realm_id=request.realm_id,
        transaction_ids=request.transaction_ids,
    )


@router.get("/sync-runs/{run_id}")
async def sync_run(
    run_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.get_sync_run(run_id)


@router.post("/sync-items/{item_id}/retry")
async def retry_sync_item(item_id: str) -> dict[str, object]:
    raise InvalidStateError(
        "QuickBooks execution is not authorized; retry remains disabled.",
        details={"item_id": item_id, "execution_authorized": False},
    )
