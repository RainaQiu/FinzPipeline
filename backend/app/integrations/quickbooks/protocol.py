"""Small, credential-free contract for posting already-approved QBO entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class QboCreateResult:
    entity_id: str
    sync_token: str | None = None


class QuickBooksGateway(Protocol):
    async def create_entity(
        self,
        kind: str,
        payload: Mapping[str, object],
        *,
        request_id: str,
    ) -> QboCreateResult: ...


class QboGatewayError(RuntimeError):
    """Sanitized gateway failure, without upstream response contents."""

    def __init__(
        self,
        status: int | None = None,
        code: str = "gateway_error",
        retryable: bool | None = None,
        message: str = "QuickBooks request failed",
    ) -> None:
        self.status = status
        self.code = code
        self.retryable = (
            retryable
            if retryable is not None
            else code not in {"missing", "invariant"}
            and (status is None or status == 429 or status >= 500)
        )
        self.safe_message = "QuickBooks request failed"
        super().__init__(self.safe_message)


class QboWriteNotAuthorizedError(PermissionError):
    """Raised before any gateway call when QBO writes are not explicitly enabled."""
