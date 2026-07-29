"""Cash-basis P&L endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_ledger_bridge
from app.services.ledger_bridge import LedgerBridgeService


router = APIRouter(prefix="/api/v1/reports/pnl", tags=["reports"])


@router.get("")
async def pnl(
    start_date: date,
    end_date: date,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.pnl(start_date, end_date)


@router.get("/accounts/{account_number}/transactions")
async def account_transactions(
    account_number: str,
    start_date: date,
    end_date: date,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.pnl_account_transactions(account_number, start_date, end_date)
