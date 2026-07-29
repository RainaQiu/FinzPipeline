"""Mongo pipeline-context documents use stable fields for transaction lookup."""

from datetime import datetime, timezone

import pytest

from app.domain.demo import PipelineContext
from app.repositories.mongo import _MongoPipelineContextRepository


class _PipelineContextCollection:
    def __init__(self) -> None:
        self.document = None
        self.last_query = None

    async def replace_one(self, query, document, *, upsert):
        self.last_query = query
        self.document = document

    async def find_one(self, query):
        self.last_query = query
        if (
            self.document is not None
            and query.get("transaction_ids")
            in self.document["transaction_ids"]
        ):
            return self.document
        return None


@pytest.mark.asyncio
async def test_transaction_lookup_uses_fixed_array_field_not_dynamic_path():
    collection = _PipelineContextCollection()
    repository = _MongoPipelineContextRepository(collection)
    transaction_id = "finz-test.transaction.$literal"
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    context = PipelineContext(
        id="context-1",
        upload_id="upload-1",
        status="completed",
        transaction_statuses={
            transaction_id: {"duplicate_status": "canonical"}
        },
        transfer_pairs={},
        counts={"raw": 2, "unique": 1},
        created_at=now,
        updated_at=now,
    )

    await repository.upsert(context)

    assert collection.document["transaction_statuses"] == [
        {
            "transaction_id": transaction_id,
            "view": {"duplicate_status": "canonical"},
        }
    ]
    assert collection.document["transaction_ids"] == [transaction_id]
    assert await repository.get_for_transaction(transaction_id) == context
    assert collection.last_query == {"transaction_ids": transaction_id}
