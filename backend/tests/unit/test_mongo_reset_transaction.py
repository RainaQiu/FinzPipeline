from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.mongo import _MongoDemoResetRepository
from app.repositories.protocols import DemoResetLeaseLostError


class _FakeCollection:
    def __init__(self, database, name: str) -> None:
        self.database = database
        self.name = name
        self.deleted = False

    async def find_one_and_update(self, query, update, **kwargs):
        assert kwargs["session"] is self.database.session
        if self.database.owner != query["id"]:
            return None
        self.database.pending_renewal = query["id"]
        return {"id": query["id"]}

    async def delete_many(self, query, **kwargs):
        assert kwargs["session"] is self.database.session
        self.database.delete_attempted = True
        self.database.pending_delete = self


class _FakeSession:
    def __init__(self, database) -> None:
        self.database = database
        self.transaction_options = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def with_transaction(self, callback, **kwargs):
        self.transaction_options = kwargs
        await callback(self)
        self.database.owner = "owner-b"
        self.database.pending_renewal = None
        self.database.pending_delete = None
        await callback(self)


class _FakeClient:
    def __init__(self, database) -> None:
        self.database = database

    def start_session(self):
        return self.database.session


class _FakeDatabase:
    def __init__(self) -> None:
        self.owner = "owner-a"
        self.pending_renewal = None
        self.pending_delete = None
        self.delete_attempted = False
        self.collections = {}
        self.session = _FakeSession(self)
        self.client = _FakeClient(self)

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection(self, name))


@pytest.mark.asyncio
async def test_takeover_during_transaction_aborts_delete_and_fences_old_owner():
    database = _FakeDatabase()
    repository = _MongoDemoResetRepository(database)
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)

    with pytest.raises(DemoResetLeaseLostError):
        await repository.clear_shared_workspace(
            lease_id="owner-a",
            clock=lambda: now,
            lease_duration=timedelta(minutes=5),
        )

    assert database["raw_records"].deleted is False
    assert database.delete_attempted is True
    assert database.pending_delete is None
    assert database.session.transaction_options["max_commit_time_ms"] == 5_000
