"""Lease-protected reset orchestration for the single shared demo workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from app.domain.demo import ExecutionLease, ResetRun
from app.repositories.protocols import DemoResetLeaseLostError, UnitOfWork


class DemoResetInProgressError(RuntimeError):
    """Raised when another shared-workspace operation owns the execution lease."""


@dataclass(frozen=True, slots=True)
class DemoResetResult:
    status: str = "reset_complete"
    scope: str = "shared_demo_workspace"
    qbo_connection: str = "preserved"


class DemoResetService:
    """Clear only repository-defined demo data while preserving configuration."""

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._lease_duration = lease_duration

    async def reset_shared_workspace(self) -> DemoResetResult:
        now = self._clock()
        run_id = self._id_factory()
        lease_id = f"demo-reset:{run_id}"
        lease = ExecutionLease(
            id=lease_id,
            acquired_at=now,
            expires_at=now + self._lease_duration,
        )
        if not await self._unit_of_work.execution_leases.acquire(lease, now=now):
            raise DemoResetInProgressError("Shared workspace reset already in progress")

        try:
            await self._unit_of_work.demo_reset.clear_shared_workspace(
                lease_id=lease_id,
                clock=self._clock,
                lease_duration=self._lease_duration,
            )
            completed_at = self._clock()
            await self._unit_of_work.demo_reset.add(
                ResetRun(
                    id=run_id,
                    status="completed",
                    started_at=now,
                    completed_at=completed_at,
                )
            )
            return DemoResetResult()
        except Exception as error:
            completed_at = self._clock()
            error_code = (
                "lease_lost"
                if isinstance(error, DemoResetLeaseLostError)
                else "repository_error"
            )
            try:
                await self._unit_of_work.demo_reset.add(
                    ResetRun(
                        id=run_id,
                        status="failed",
                        started_at=now,
                        completed_at=completed_at,
                        error_code=error_code,
                        stage="clear_shared_workspace",
                    )
                )
            except Exception:
                pass
            raise
        finally:
            await self._unit_of_work.execution_leases.release(lease_id)
