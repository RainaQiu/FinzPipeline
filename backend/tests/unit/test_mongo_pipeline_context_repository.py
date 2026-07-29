"""Mongo pipeline-context documents use stable fields for transaction lookup."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.domain.demo import PipelineContext, UploadRecord
from app.repositories.mongo import (
    _MongoPipelineContextRepository,
    _MongoUploadRepository,
)
from app.repositories.protocols import InvalidStateTransitionError


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


class _UploadCollection:
    def __init__(self) -> None:
        self.document = None
        self.last_transition_query = None

    async def insert_one(self, document):
        self.document = document

    async def find_one(self, query):
        if self.document is not None and self.document["_id"] == query["_id"]:
            return self.document
        return None

    async def find_one_and_replace(self, query, document, *, return_document):
        self.last_transition_query = query
        if self.document is None:
            return None
        if any(self.document.get(key) != value for key, value in query.items()):
            return None
        self.document = document
        return document


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


@pytest.mark.asyncio
async def test_upload_transition_uses_one_atomic_expected_status_filter():
    collection = _UploadCollection()
    repository = _MongoUploadRepository(collection)
    upload = UploadRecord(
        id="upload-cas",
        original_filename="source.csv",
        media_type="text/csv",
        sha256="a" * 64,
        data=b"source",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    await repository.add(upload)
    processing = replace(upload, status="processing")

    assert (
        await repository.transition_status(
            processing, expected_status="uploaded"
        )
        == processing
    )
    assert collection.last_transition_query == {
        "_id": upload.id,
        "status": "uploaded",
        "original_filename": upload.original_filename,
        "media_type": upload.media_type,
        "sha256": upload.sha256,
        "data": upload.data,
        "created_at": upload.created_at,
    }
    with pytest.raises(InvalidStateTransitionError):
        await repository.transition_status(
            processing, expected_status="uploaded"
        )
