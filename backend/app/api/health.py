"""Liveness and readiness endpoints."""

import asyncio

from fastapi import APIRouter, HTTPException, Request


router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "service": "finz-ledger-bridge",
        "environment": request.app.state.settings.qbo_environment,
    }


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    unit_of_work = request.app.state.unit_of_work
    ping = getattr(unit_of_work, "ping", None)
    if ping is not None:
        try:
            if not await asyncio.wait_for(ping(), timeout=2):
                raise RuntimeError("database ping returned false")
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Required repository is unavailable"
            ) from exc
    return {"status": "ready"}
