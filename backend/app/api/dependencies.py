"""FastAPI dependency accessors."""

from fastapi import Request

from app.services.ledger_bridge import LedgerBridgeService


def get_ledger_bridge(request: Request) -> LedgerBridgeService:
    return request.app.state.ledger_bridge
