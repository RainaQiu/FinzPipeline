"""Human classification decision endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_ledger_bridge
from app.domain.classification import TransactionType
from app.services.ledger_bridge import LedgerBridgeService


router = APIRouter(tags=["classifications"])


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_number: str = Field(pattern=r"^\d{4}$")
    transaction_type: TransactionType
    explanation: str = Field(min_length=1, max_length=1000)


class BulkApproveRequest(BaseModel):
    transaction_ids: list[str] = Field(min_length=1, max_length=250)


@router.post("/api/v1/transactions/{transaction_id}/approve")
async def approve(
    transaction_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.approve_transaction(transaction_id)


@router.post("/api/v1/transactions/{transaction_id}/correct")
async def correct(
    transaction_id: str,
    request: CorrectionRequest,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.correct_transaction(
        transaction_id,
        account_number=request.account_number,
        transaction_type=request.transaction_type,
        explanation=request.explanation,
    )


@router.post("/api/v1/classifications/bulk-approve")
async def bulk_approve(
    request: BulkApproveRequest,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.bulk_approve(request.transaction_ids)


@router.post("/api/v1/classifications/run")
async def run_classifications() -> dict[str, object]:
    return {"status": "already_classified", "execution": "deterministic"}
