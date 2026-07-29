"""Real MongoDB reconnect persistence check.

Container restart persistence is verified separately by the local operations
procedure; this test confirms repository data survives client/UoW replacement.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
import pytest
from pymongo import AsyncMongoClient

from app.domain.transactions import RawRecord
from app.repositories.mongo import MongoUnitOfWork


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("FINZ_RUN_MONGO_INTEGRATION") != "1",
        reason="set FINZ_RUN_MONGO_INTEGRATION=1 to use real local MongoDB",
    ),
]


async def test_repository_data_survives_client_reconnect():
    uri = os.environ["FINZ_MONGODB_URI"]
    database_name = "finz_ledger_bridge_test"
    record = RawRecord(
        id="persistence-marker",
        source_filename="finz-test.csv",
        source_file_sha256="a" * 64,
        source_sheet="CSV",
        source_row_number=2,
        raw_values={"marker": "finz-test"},
        raw_row_sha256="b" * 64,
        ingested_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    first_client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
    try:
        await first_client.drop_database(database_name)
        first_uow = MongoUnitOfWork(first_client, database_name)
        await first_uow.create_indexes()
        await first_uow.raw_records.add(record)
    finally:
        await first_client.close()

    second_client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
    try:
        second_uow = MongoUnitOfWork(second_client, database_name)
        assert await second_uow.raw_records.get(record.id) == record
    finally:
        assert database_name == "finz_ledger_bridge_test"
        await second_client.drop_database(database_name)
        await second_client.close()


async def test_owned_mongo_uow_can_be_reused_across_contexts_and_closed_explicitly():
    uow = MongoUnitOfWork.from_uri(
        os.environ["FINZ_MONGODB_URI"], "finz_ledger_bridge_test"
    )
    try:
        async with uow:
            await uow.create_indexes()
        async with uow:
            assert await uow.ping() is True
    finally:
        await uow.aclose()
