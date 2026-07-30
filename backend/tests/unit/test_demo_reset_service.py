from datetime import datetime, timedelta, timezone

import pytest

from app.domain.demo import ExecutionLease, QboConnection, ResetRun, UploadRecord
from app.repositories.memory import InMemoryUnitOfWork
from app.services.demo_reset import (
    DemoResetInProgressError,
    DemoResetLeaseLostError,
    DemoResetService,
)


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
    stored_reset = uow.demo_reset

    class FailingResetRepository:
        async def clear_shared_workspace(self, *, ensure_owner) -> None:
            await ensure_owner()
            raise RuntimeError("mongodb://user:secret@example/reset failed")

        async def add(self, run):
            return await stored_reset.add(run)

        async def get(self, run_id):
            return await stored_reset.get(run_id)

    uow.demo_reset = FailingResetRepository()
    service = DemoResetService(
        uow,
        clock=lambda: NOW,
        id_factory=lambda: "finz-test-failed-reset",
    )

    with pytest.raises(RuntimeError):
        await service.reset_shared_workspace()

    failed = await uow.demo_reset.get("finz-test-failed-reset")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "repository_error"
    assert failed.stage == "clear_shared_workspace"
    assert "secret" not in repr(failed)
    replacement = ExecutionLease(
        id="finz-test-after-failure",
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert await uow.execution_leases.acquire(replacement, now=NOW) is True
    await uow.execution_leases.release(replacement.id)
    uow.demo_reset = stored_reset
    await uow.uploads.add(_upload())
    retry = DemoResetService(
        uow,
        clock=lambda: NOW,
        id_factory=lambda: "finz-test-retry-reset",
    )

    assert (await retry.reset_shared_workspace()).status == "reset_complete"
    assert await uow.uploads.get("finz-test-reset-upload") is None
    assert (await uow.demo_reset.get("finz-test-failed-reset")).status == "failed"


@pytest.mark.asyncio
async def test_reset_service_stops_when_lease_owner_is_lost() -> None:
    uow = InMemoryUnitOfWork()
    stored_reset = uow.demo_reset

    class LostOwnerResetRepository:
        async def clear_shared_workspace(self, *, ensure_owner) -> None:
            await ensure_owner()
            await uow.execution_leases.release(
                "demo-reset:finz-test-lost-owner"
            )
            takeover = ExecutionLease(
                id="finz-test-takeover",
                acquired_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )
            assert await uow.execution_leases.acquire(takeover, now=NOW)
            await ensure_owner()
            raise AssertionError("old reset owner continued after takeover")

        async def add(self, run):
            return await stored_reset.add(run)

        async def get(self, run_id):
            return await stored_reset.get(run_id)

    uow.demo_reset = LostOwnerResetRepository()
    service = DemoResetService(
        uow,
        clock=lambda: NOW,
        id_factory=lambda: "finz-test-lost-owner",
    )

    with pytest.raises(DemoResetLeaseLostError):
        await service.reset_shared_workspace()

    failed = await uow.demo_reset.get("finz-test-lost-owner")
    assert failed is not None
    assert failed.error_code == "lease_lost"
