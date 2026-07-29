"""Transaction query and lineage endpoints."""

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_ledger_bridge
from app.services.ledger_bridge import LedgerBridgeService


router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    approval: str | None = Query(default=None),
    account: str | None = Query(default=None, pattern=r"^\d{4}$"),
    duplicate: str | None = None,
    risk: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=250),
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.list_transactions(
        month=month,
        approval=approval,
        account=account,
        duplicate=duplicate,
        risk=risk,
        search=search,
        offset=offset,
        limit=limit,
    )


@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.get_transaction(transaction_id)


@router.get("/{transaction_id}/lineage")
async def get_lineage(
    transaction_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.get_lineage(transaction_id)
