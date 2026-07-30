from datetime import datetime, timedelta, timezone

import pytest

from app.domain.demo import ExecutionLease, QboConnection, ResetRun, UploadRecord
from app.repositories.memory import InMemoryUnitOfWork
from app.services.demo_reset import DemoResetInProgressError, DemoResetService


NOW = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _connection() -> QboConnection:
    return QboConnection(
        realm_id="finz-test-realm",
        company_name="BrightFix Home Services LLC",
        encrypted_access_token="encrypted-access",
        encrypted_refresh_token="encrypted-refresh",
        access_expires_at=NOW + timedelta(hours=1),
        refresh_expires_at=NOW + timedelta(days=30),
        updated_at=NOW,
    )


def _upload() -> UploadRecord:
    return UploadRecord(
        id="finz-test-reset-upload",
        original_filename="brightfix.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sha256="a" * 64,
        data=b"synthetic challenge data",
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_reset_service_clears_workspace_preserves_qbo_and_releases_lease() -> None:
    uow = InMemoryUnitOfWork()
    connection = _connection()
    await uow.uploads.add(_upload())
    await uow.qbo_connection.upsert(connection)
    service = DemoResetService(
        uow,
        clock=lambda: NOW,
        id_factory=lambda: "finz-test-reset-run",
    )

    result = await service.reset_shared_workspace()

    assert result.status == "reset_complete"
    assert result.scope == "shared_demo_workspace"
    assert result.qbo_connection == "preserved"
    assert await uow.uploads.get("finz-test-reset-upload") is None
    assert await uow.qbo_connection.get() == connection
    completed_run = ResetRun(
        id="finz-test-reset-run",
        status="completed",
        started_at=NOW,
        completed_at=NOW,
    )
    assert await uow.demo_reset.add(completed_run) == completed_run
    replacement = ExecutionLease(
        id="finz-test-replacement",
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert await uow.execution_leases.acquire(replacement, now=NOW) is True


@pytest.mark.asyncio
async def test_reset_service_rejects_concurrent_run_without_clearing_data() -> None:
    uow = InMemoryUnitOfWork()
    await uow.uploads.add(_upload())
    active = ExecutionLease(
        id="other-reset",
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert await uow.execution_leases.acquire(active, now=NOW) is True
    service = DemoResetService(
        uow,
        clock=lambda: NOW,
        id_factory=lambda: "finz-test-rejected-reset",
    )

    with pytest.raises(DemoResetInProgressError):
        await service.reset_shared_workspace()

    assert await uow.uploads.get("finz-test-reset-upload") is not None


@pytest.mark.asyncio
async def test_reset_service_releases_lease_when_repository_clear_fails() -> None:
    uow = InMemoryUnitOfWork()

    class FailingResetRepository:
        async def clear_shared_workspace(self) -> None:
            raise RuntimeError("mongodb://user:secret@example/reset failed")

        async def add(self, run):
            return run

    uow.demo_reset = FailingResetRepository()
    service = DemoResetService(
        uow,
        clock=lambda: NOW,
        id_factory=lambda: "finz-test-failed-reset",
    )

    with pytest.raises(RuntimeError):
        await service.reset_shared_workspace()

    replacement = ExecutionLease(
        id="finz-test-after-failure",
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert await uow.execution_leases.acquire(replacement, now=NOW) is True
