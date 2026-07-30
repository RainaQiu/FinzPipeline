"""Read-first QuickBooks Sandbox and guarded sync planning endpoints."""

from datetime import date, datetime, timedelta, timezone
from secrets import token_urlsafe
from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_ledger_bridge
from app.services.ledger_bridge import InvalidStateError, LedgerBridgeService
from app.services.qbo_sync import process_outbox_item
from app.domain.demo import ExecutionLease


router = APIRouter(prefix="/api/v1/integrations/qbo", tags=["QuickBooks"])


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realm_id: str | None = Field(default=None, min_length=1, max_length=200)
    transaction_ids: list[str] | None = Field(default=None, max_length=250)


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_token: str = Field(min_length=20, max_length=200)
    confirmation: str = Field(min_length=1, max_length=100)


WRITE_CONFIRMATION = "POST TO BRIGHTFIX QBO SANDBOX"


@router.get("/status")
async def qbo_status(request: Request) -> dict[str, object]:
    runtime = request.app.state.qbo_runtime
    if runtime is not None:
        return await runtime.status()
    return {
        "mode": "demo_local",
        "connected": False,
        "company_name": None,
        "execution_authorized": False,
        "transaction_write_network_accessed": False,
    }


@router.get("/accounts/preflight")
async def account_preflight(request: Request) -> dict[str, object]:
    runtime = request.app.state.qbo_runtime
    if runtime is None:
        raise HTTPException(503, "QBO Sandbox read integration is unavailable")
    try:
        return await runtime.account_preflight()
    except Exception:
        raise HTTPException(502, "QBO account preflight failed") from None


@router.get("/reports/profit-and-loss")
async def profit_and_loss(
    request: Request, start_date: date, end_date: date
) -> dict[str, object]:
    runtime = request.app.state.qbo_runtime
    if runtime is None:
        raise HTTPException(503, "QBO Sandbox read integration is unavailable")
    try:
        return await runtime.profit_and_loss(start_date, end_date)
    except Exception:
        raise HTTPException(502, "QBO Profit and Loss read failed") from None


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync(
    payload: SyncRequest,
    request: Request,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    expected_realm = request.app.state.core_settings.qbo_expected_realm_id
    realm_id = expected_realm or payload.realm_id
    if realm_id is None:
        raise HTTPException(503, "QBO Sandbox realm is not configured")
    if expected_realm is not None and payload.realm_id not in {None, expected_realm}:
        raise HTTPException(400, "Unexpected QBO Sandbox company")
    return await service.plan_qbo_sync(
        realm_id=realm_id,
        transaction_ids=payload.transaction_ids,
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


@router.get("/sync-items/{item_id}/prewrite")
async def prewrite(item_id: str, request: Request) -> dict[str, object]:
    item = await request.app.state.unit_of_work.outbox.get(item_id)
    if item is None:
        raise HTTPException(404, "Outbox item not found")
    return {
        "item_id": item.id,
        "entity_type": item.payload_kind,
        "status": item.status.value,
        "amount": _payload_amount(item.payload),
        "required_confirmation": WRITE_CONFIRMATION,
        "writes_enabled": request.app.state.core_settings.qbo_sandbox_writes_enabled,
    }


@router.post("/sync-items/{item_id}/execute")
async def execute_sync_item(
    item_id: str, payload: ExecuteRequest, request: Request
) -> dict[str, object]:
    settings = request.app.state.core_settings
    runtime = request.app.state.qbo_runtime
    if not settings.qbo_sandbox_writes_enabled or runtime is None:
        raise HTTPException(403, "QBO Sandbox writes are disabled")
    if payload.confirmation != WRITE_CONFIRMATION:
        raise HTTPException(400, "Explicit QBO Sandbox confirmation is required")
    if not await request.app.state.demo_access_grant_service.consume(
        payload.grant_token
    ):
        raise HTTPException(401, "Access grant is invalid or expired")
    now = datetime.now(timezone.utc)
    lease = ExecutionLease(
        id=f"qbo-write:{token_urlsafe(16)}",
        acquired_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    uow = request.app.state.unit_of_work
    if not await uow.execution_leases.acquire(lease, now=now):
        raise HTTPException(409, "Another protected operation is in progress")
    try:
        await runtime.account_preflight()
        item = await process_outbox_item(
            item_id, runtime, uow, allow_writes=True
        )
        return {
            "item_id": item.id,
            "status": item.status.value,
            "qbo_entity_id": item.qbo_entity_id,
        }
    except Exception:
        raise HTTPException(502, "QBO Sandbox write failed") from None
    finally:
        await uow.execution_leases.release(lease.id)


def _payload_amount(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        try:
            payload = dict(payload)
        except (TypeError, ValueError):
            return None
    if "Amount" in payload:
        return str(payload["Amount"])
    lines = payload.get("Line")
    if isinstance(lines, (list, tuple)) and lines and isinstance(lines[0], Mapping):
        return str(lines[0].get("Amount")) if lines[0].get("Amount") is not None else None
    return None
