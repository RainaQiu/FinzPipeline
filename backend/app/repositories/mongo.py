"""MongoDB repositories with the same contracts as the in-memory implementation."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from bson.codec_options import CodecOptions
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.domain.accounting import OutboxItem, OutboxStatus
from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.demo import (
    DemoGrant,
    ExecutionLease,
    PipelineContext,
    QboConnection,
    ReconciliationRunRecord,
    ResetRun,
    SyncRunRecord,
    UploadRecord,
)
from app.domain.transactions import Direction, NormalizedTransaction, RawRecord
from app.repositories.protocols import (
    AuditEvent,
    ImmutableRecordError,
    InvalidStateTransitionError,
    OAuthState,
    OAuthStateExpiredError,
    TransactionContextConflictError,
)


def _validate_page(offset: int, limit: int | None) -> None:
    if offset < 0 or limit is not None and limit < 0:
        raise ValueError("offset and limit must not be negative")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_thaw(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _model_document(model: object) -> dict[str, object]:
    return {
        field.name: _thaw(getattr(model, field.name))
        for field in fields(model)  # type: ignore[arg-type]
    }


def _without_mongo_id(document: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in document.items() if key != "_id"}


def _raw_from_document(document: Mapping[str, object]) -> RawRecord:
    return RawRecord(**_without_mongo_id(document))  # type: ignore[arg-type]


def _transaction_document(transaction: NormalizedTransaction) -> dict[str, object]:
    document = _model_document(transaction)
    document["transaction_date"] = transaction.transaction_date.isoformat()
    document["posted_date"] = transaction.posted_date.isoformat()
    return document


def _transaction_from_document(document: Mapping[str, object]) -> NormalizedTransaction:
    values = _without_mongo_id(document)
    values["transaction_date"] = date.fromisoformat(str(values["transaction_date"]))
    values["posted_date"] = date.fromisoformat(str(values["posted_date"]))
    values["direction"] = Direction(str(values["direction"]))
    return NormalizedTransaction(**values)  # type: ignore[arg-type]


def _decision_from_document(document: Mapping[str, object]) -> ClassificationDecision:
    values = _without_mongo_id(document)
    values["transaction_type"] = TransactionType(str(values["transaction_type"]))
    values["source"] = DecisionSource(str(values["source"]))
    values["approval_status"] = ApprovalStatus(str(values["approval_status"]))
    return ClassificationDecision(**values)  # type: ignore[arg-type]


def _outbox_from_document(document: Mapping[str, object]) -> OutboxItem:
    values = _without_mongo_id(document)
    values["status"] = OutboxStatus(str(values["status"]))
    return OutboxItem(**values)  # type: ignore[arg-type]


def _oauth_from_document(document: Mapping[str, object]) -> OAuthState:
    return OAuthState(
        state_hash=str(document["state_hash"]),
        expires_at=document["expires_at"],  # type: ignore[arg-type]
    )


def _audit_from_document(document: Mapping[str, object]) -> AuditEvent:
    return AuditEvent(
        event_type=str(document["event_type"]),
        payload=document["payload"],  # type: ignore[arg-type]
        occurred_at=document["occurred_at"],  # type: ignore[arg-type]
        sequence=int(document["sequence"]),
    )


def _upload_from_document(document: Mapping[str, object]) -> UploadRecord:
    return UploadRecord(**_without_mongo_id(document))  # type: ignore[arg-type]


def _pipeline_context_from_document(
    document: Mapping[str, object],
) -> PipelineContext:
    values = _without_mongo_id(document)
    values.pop("transaction_ids", None)
    stored_statuses = values.get("transaction_statuses")
    if isinstance(stored_statuses, list):
        values["transaction_statuses"] = {
            str(item["transaction_id"]): item["view"]
            for item in stored_statuses
            if isinstance(item, Mapping)
            and "transaction_id" in item
            and "view" in item
        }
    return PipelineContext(**values)  # type: ignore[arg-type]


def _sync_run_from_document(document: Mapping[str, object]) -> SyncRunRecord:
    return SyncRunRecord(**_without_mongo_id(document))  # type: ignore[arg-type]


def _reconciliation_run_from_document(
    document: Mapping[str, object],
) -> ReconciliationRunRecord:
    return ReconciliationRunRecord(
        **_without_mongo_id(document)  # type: ignore[arg-type]
    )


def _demo_grant_from_document(document: Mapping[str, object]) -> DemoGrant:
    return DemoGrant(**_without_mongo_id(document))  # type: ignore[arg-type]


def _qbo_connection_from_document(
    document: Mapping[str, object],
) -> QboConnection:
    values = _without_mongo_id(document)
    values.pop("singleton", None)
    return QboConnection(**values)  # type: ignore[arg-type]


class _MongoRawRecordRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def add(self, record: RawRecord) -> RawRecord:
        document = _model_document(record)
        document["_id"] = record.id
        try:
            await self._collection.insert_one(document)
            return record
        except DuplicateKeyError:
            existing = await self.get(record.id)
            if (
                existing is not None
                and replace(existing, ingested_at=record.ingested_at) == record
            ):
                return existing
            raise ImmutableRecordError(f"raw record {record.id!r} is immutable") from None

    async def get(self, record_id: str) -> RawRecord | None:
        document = await self._collection.find_one({"_id": record_id})
        return _raw_from_document(document) if document is not None else None

    async def list(
        self, *, offset: int = 0, limit: int | None = None
    ) -> tuple[RawRecord, ...]:
        _validate_page(offset, limit)
        cursor = self._collection.find({}).sort("_id", ASCENDING).skip(offset)
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple([_raw_from_document(item) async for item in cursor])


class _MongoTransactionRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def add(self, transaction: NormalizedTransaction) -> NormalizedTransaction:
        document = _transaction_document(transaction)
        document["_id"] = transaction.id
        try:
            await self._collection.insert_one(document)
            return transaction
        except DuplicateKeyError:
            existing = await self.get(transaction.id)
            if existing == transaction:
                return existing
            raise ImmutableRecordError(
                f"transaction {transaction.id!r} is immutable"
            ) from None

    async def get(self, transaction_id: str) -> NormalizedTransaction | None:
        document = await self._collection.find_one({"_id": transaction_id})
        return _transaction_from_document(document) if document is not None else None

    async def list(
        self,
        *,
        raw_record_id: str | None = None,
        bank_transaction_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[NormalizedTransaction, ...]:
        _validate_page(offset, limit)
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        query: dict[str, object] = {}
        if raw_record_id is not None:
            query["raw_record_id"] = raw_record_id
        if bank_transaction_id is not None:
            query["bank_transaction_id"] = bank_transaction_id
        date_filter: dict[str, str] = {}
        if start_date is not None:
            date_filter["$gte"] = start_date.isoformat()
        if end_date is not None:
            date_filter["$lte"] = end_date.isoformat()
        if date_filter:
            query["transaction_date"] = date_filter
        cursor = (
            self._collection.find(query)
            .sort([("transaction_date", ASCENDING), ("_id", ASCENDING)])
            .skip(offset)
        )
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple([_transaction_from_document(item) async for item in cursor])


class _MongoClassificationRepository:
    def __init__(self, collection, counters) -> None:
        self._collection = collection
        self._counters = counters

    async def append(self, decision: ClassificationDecision) -> ClassificationDecision:
        existing_document = await self._collection.find_one({"_id": decision.id})
        if existing_document is not None:
            existing = _decision_from_document(existing_document)
            if replace(existing, version=decision.version) == decision:
                return existing
            raise ImmutableRecordError(
                f"classification decision {decision.id!r} is append-only"
            )
        counter = await self._counters.find_one_and_update(
            {"_id": f"classification:{decision.transaction_id}"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        stored = replace(decision, version=int(counter["value"]))
        document = _model_document(stored)
        document["_id"] = stored.id
        try:
            await self._collection.insert_one(document)
            return stored
        except DuplicateKeyError:
            existing_document = await self._collection.find_one({"_id": decision.id})
            if existing_document is not None:
                existing = _decision_from_document(existing_document)
                if replace(existing, version=decision.version) == decision:
                    return existing
            raise ImmutableRecordError(
                f"classification decision {decision.id!r} is append-only"
            ) from None

    async def latest(self, transaction_id: str) -> ClassificationDecision | None:
        document = await self._collection.find_one(
            {"transaction_id": transaction_id}, sort=[("version", -1)]
        )
        return _decision_from_document(document) if document is not None else None

    async def history(
        self, transaction_id: str, *, offset: int = 0, limit: int | None = None
    ) -> tuple[ClassificationDecision, ...]:
        _validate_page(offset, limit)
        cursor = (
            self._collection.find({"transaction_id": transaction_id})
            .sort("version", ASCENDING)
            .skip(offset)
        )
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple([_decision_from_document(item) async for item in cursor])


class _MongoOutboxRepository:
    _ALLOWED = {
        OutboxStatus.PENDING: {OutboxStatus.PROCESSING},
        OutboxStatus.PROCESSING: {
            OutboxStatus.SUCCEEDED,
            OutboxStatus.RETRYABLE_FAILED,
            OutboxStatus.PERMANENT_FAILED,
        },
        OutboxStatus.RETRYABLE_FAILED: {OutboxStatus.PROCESSING},
        OutboxStatus.SUCCEEDED: set(),
        OutboxStatus.PERMANENT_FAILED: set(),
    }

    def __init__(self, collection) -> None:
        self._collection = collection

    async def add(self, item: OutboxItem) -> OutboxItem:
        key = item.idempotency_key or item.id
        stored = item if item.idempotency_key else replace(item, idempotency_key=key)
        document = _model_document(stored)
        document["_id"] = stored.id
        try:
            await self._collection.insert_one(document)
            return stored
        except DuplicateKeyError:
            existing_document = await self._collection.find_one(
                {"idempotency_key": key}
            )
            if existing_document is not None:
                return _outbox_from_document(existing_document)
            existing = await self.get(stored.id)
            if existing == stored:
                return existing
            raise ImmutableRecordError(f"outbox item {stored.id!r} is immutable") from None

    async def get(self, item_id: str) -> OutboxItem | None:
        document = await self._collection.find_one({"_id": item_id})
        return _outbox_from_document(document) if document is not None else None

    async def claim_pending(self, *, limit: int = 1) -> tuple[OutboxItem, ...]:
        if limit < 0:
            raise ValueError("limit must not be negative")
        claimed: list[OutboxItem] = []
        for _ in range(limit):
            document = await self._collection.find_one_and_update(
                {"status": OutboxStatus.PENDING.value},
                {
                    "$set": {
                        "status": OutboxStatus.PROCESSING.value,
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$inc": {"attempt_count": 1},
                },
                sort=[("created_at", ASCENDING), ("_id", ASCENDING)],
                return_document=ReturnDocument.AFTER,
            )
            if document is None:
                break
            claimed.append(_outbox_from_document(document))
        return tuple(claimed)

    async def transition(
        self,
        item_id: str,
        status: OutboxStatus,
        *,
        updated_at: datetime | None = None,
        next_attempt_at: datetime | None = None,
        last_error_code: str | None = None,
        qbo_entity_id: str | None = None,
        sync_token: str | None = None,
    ) -> OutboxItem:
        current_document = await self._collection.find_one({"_id": item_id})
        if current_document is None:
            raise KeyError(item_id)
        current = _outbox_from_document(current_document)
        if status not in self._ALLOWED[current.status]:
            raise InvalidStateTransitionError(
                f"cannot transition {current.status} to {status}"
            )
        updates: dict[str, object] = {
            "status": status.value,
            "updated_at": updated_at or datetime.now(timezone.utc),
            "next_attempt_at": next_attempt_at,
            "last_error_code": last_error_code,
        }
        if qbo_entity_id is not None:
            updates["qbo_entity_id"] = qbo_entity_id
        if sync_token is not None:
            updates["sync_token"] = sync_token
        document = await self._collection.find_one_and_update(
            {"_id": item_id, "status": current.status.value},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise InvalidStateTransitionError(
                f"outbox item {item_id!r} changed concurrently"
            )
        return _outbox_from_document(document)


class _MongoOAuthStateRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    @staticmethod
    def _hash(state: str) -> str:
        return sha256(state.encode("utf-8")).hexdigest()

    async def put(self, state: str, *, expires_at: datetime) -> OAuthState:
        saved = OAuthState(state_hash=self._hash(state), expires_at=expires_at)
        await self._collection.replace_one(
            {"_id": saved.state_hash},
            {
                "_id": saved.state_hash,
                "state_hash": saved.state_hash,
                "expires_at": saved.expires_at,
            },
            upsert=True,
        )
        return saved

    async def consume(
        self, state: str, *, now: datetime | None = None
    ) -> OAuthState | None:
        state_hash = self._hash(state)
        document = await self._collection.find_one_and_delete({"_id": state_hash})
        if document is None:
            return None
        saved = _oauth_from_document(document)
        if saved.expires_at <= (now or datetime.now(timezone.utc)):
            raise OAuthStateExpiredError("OAuth state has expired")
        return saved


class _MongoAuditRepository:
    def __init__(self, collection, counters) -> None:
        self._collection = collection
        self._counters = counters

    async def append(self, event: AuditEvent) -> AuditEvent:
        counter = await self._counters.find_one_and_update(
            {"_id": "audit"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        stored = replace(event, sequence=int(counter["value"]))
        document = _model_document(stored)
        document["_id"] = stored.sequence
        await self._collection.insert_one(document)
        return stored

    async def list(
        self, *, offset: int = 0, limit: int | None = None
    ) -> tuple[AuditEvent, ...]:
        _validate_page(offset, limit)
        cursor = self._collection.find({}).sort("sequence", ASCENDING).skip(offset)
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple([_audit_from_document(item) async for item in cursor])


class _MongoUploadRepository:
    _ALLOWED = {
        "uploaded": {"processing"},
        "failed": {"processing"},
        "processing": {"processing", "completed", "failed"},
        "completed": set(),
    }

    def __init__(self, collection) -> None:
        self._collection = collection

    async def add(self, upload: UploadRecord) -> UploadRecord:
        document = _model_document(upload)
        document["_id"] = upload.id
        try:
            await self._collection.insert_one(document)
            return upload
        except DuplicateKeyError:
            existing = await self.get(upload.id)
            if existing == upload:
                return existing
            raise ImmutableRecordError(f"upload {upload.id!r} is immutable") from None

    async def get(self, upload_id: str) -> UploadRecord | None:
        document = await self._collection.find_one({"_id": upload_id})
        return _upload_from_document(document) if document is not None else None

    async def transition_status(
        self,
        upload: UploadRecord,
        *,
        expected_status: str,
        expected_token: str | None = None,
    ) -> UploadRecord:
        if (
            upload.status not in self._ALLOWED.get(expected_status, set())
            or (
                expected_status == "processing"
                and upload.status == "processing"
                and upload.processing_token == expected_token
            )
        ):
            raise InvalidStateTransitionError(
                f"upload {upload.id!r} cannot transition "
                f"from {expected_status!r} to {upload.status!r}"
            )
        document = _model_document(upload)
        document["_id"] = upload.id
        source_filter = {
            "_id": upload.id,
            "status": expected_status,
            "processing_token": expected_token,
            "original_filename": upload.original_filename,
            "media_type": upload.media_type,
            "sha256": upload.sha256,
            "data": upload.data,
            "created_at": upload.created_at,
        }
        saved = await self._collection.find_one_and_replace(
            source_filter,
            document,
            return_document=ReturnDocument.AFTER,
        )
        if saved is not None:
            return _upload_from_document(saved)
        existing = await self.get(upload.id)
        if existing is None:
            raise KeyError(upload.id)
        if (
            existing.original_filename,
            existing.media_type,
            existing.sha256,
            existing.data,
            existing.created_at,
        ) != (
            upload.original_filename,
            upload.media_type,
            upload.sha256,
            upload.data,
            upload.created_at,
        ):
            raise ImmutableRecordError(
                f"upload {upload.id!r} source fields are immutable"
            )
        raise InvalidStateTransitionError(
            f"upload {upload.id!r} expected {expected_status!r}, "
            f"found {existing.status!r}"
        )


class _MongoPipelineContextRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def upsert(self, context: PipelineContext) -> PipelineContext:
        document = _model_document(context)
        document["_id"] = context.upload_id
        document["transaction_ids"] = sorted(context.transaction_statuses)
        document["transaction_statuses"] = [
            {
                "transaction_id": transaction_id,
                "view": _thaw(context.transaction_statuses[transaction_id]),
            }
            for transaction_id in sorted(context.transaction_statuses)
        ]
        try:
            await self._collection.replace_one(
                {"_id": context.upload_id}, document, upsert=True
            )
        except DuplicateKeyError:
            raise TransactionContextConflictError(
                "transaction already belongs to another upload"
            ) from None
        return context

    async def get(self, upload_id: str) -> PipelineContext | None:
        document = await self._collection.find_one({"_id": upload_id})
        return (
            _pipeline_context_from_document(document)
            if document is not None
            else None
        )

    async def get_for_transaction(
        self, transaction_id: str
    ) -> PipelineContext | None:
        document = await self._collection.find_one(
            {"transaction_ids": transaction_id}
        )
        return (
            _pipeline_context_from_document(document)
            if document is not None
            else None
        )


class _MongoSyncRunRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def add(self, run: SyncRunRecord) -> SyncRunRecord:
        document = _model_document(run)
        document["_id"] = run.id
        try:
            await self._collection.insert_one(document)
            return run
        except DuplicateKeyError:
            existing = await self.get(run.id)
            if existing == run:
                return existing
            raise ImmutableRecordError(f"sync run {run.id!r} is immutable") from None

    async def get(self, run_id: str) -> SyncRunRecord | None:
        document = await self._collection.find_one({"_id": run_id})
        return _sync_run_from_document(document) if document is not None else None


class _MongoReconciliationRunRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def add(self, run: ReconciliationRunRecord) -> ReconciliationRunRecord:
        document = _model_document(run)
        document["_id"] = run.id
        try:
            await self._collection.insert_one(document)
            return run
        except DuplicateKeyError:
            existing = await self.get(run.id)
            if existing == run:
                return existing
            raise ImmutableRecordError(
                f"reconciliation run {run.id!r} is immutable"
            ) from None

    async def get(self, run_id: str) -> ReconciliationRunRecord | None:
        document = await self._collection.find_one({"_id": run_id})
        return (
            _reconciliation_run_from_document(document)
            if document is not None
            else None
        )


class _MongoDemoGrantRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def issue(self, grant: DemoGrant) -> DemoGrant:
        document = _model_document(grant)
        document["_id"] = grant.token_hash
        await self._collection.replace_one(
            {"_id": grant.token_hash}, document, upsert=True
        )
        return grant

    async def consume_valid(
        self, token_hash: str, *, now: datetime
    ) -> DemoGrant | None:
        document = await self._collection.find_one_and_delete({"_id": token_hash})
        if document is None:
            return None
        grant = _demo_grant_from_document(document)
        return grant if grant.expires_at > now else None


class _MongoQboConnectionRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def upsert(self, connection: QboConnection) -> QboConnection:
        document = _model_document(connection)
        document.update({"_id": "singleton", "singleton": True})
        await self._collection.replace_one({"_id": "singleton"}, document, upsert=True)
        return connection

    async def get(self) -> QboConnection | None:
        document = await self._collection.find_one({"_id": "singleton"})
        return (
            _qbo_connection_from_document(document)
            if document is not None
            else None
        )


class _MongoExecutionLeaseRepository:
    def __init__(self, collection) -> None:
        self._collection = collection

    async def acquire(self, lease: ExecutionLease, *, now: datetime) -> bool:
        if not (lease.acquired_at <= now < lease.expires_at):
            return False
        try:
            document = await self._collection.find_one_and_update(
                {
                    "_id": "active",
                    "$or": [
                        {"expires_at": {"$lte": now}},
                        {"expires_at": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "id": lease.id,
                        "acquired_at": lease.acquired_at,
                        "expires_at": lease.expires_at,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return False
        return document is not None and document.get("id") == lease.id

    async def release(self, lease_id: str) -> None:
        await self._collection.delete_one({"_id": "active", "id": lease_id})


class _MongoDemoResetRepository:
    _WORKSPACE_COLLECTIONS = (
        "raw_records",
        "transactions",
        "classifications",
        "outbox",
        "oauth_states",
        "audit_events",
        "counters",
        "uploads",
        "pipeline_contexts",
        "sync_runs",
        "reconciliation_runs",
        "demo_grants",
        "execution_leases",
        "reset_runs",
    )

    def __init__(self, database) -> None:
        self._database = database
        self._collection = database["reset_runs"]

    async def add(self, run: ResetRun) -> ResetRun:
        document = _model_document(run)
        document["_id"] = run.id
        try:
            await self._collection.insert_one(document)
            return run
        except DuplicateKeyError:
            existing_document = await self._collection.find_one({"_id": run.id})
            if existing_document is not None:
                existing = ResetRun(
                    **_without_mongo_id(existing_document)  # type: ignore[arg-type]
                )
                if existing == run:
                    return existing
            raise ImmutableRecordError(f"reset run {run.id!r} is immutable") from None

    async def clear_shared_workspace(self) -> None:
        for collection_name in self._WORKSPACE_COLLECTIONS:
            await self._database[collection_name].delete_many({})


class MongoUnitOfWork:
    """Mongo-backed unit of work.

    The caller owns the client lifecycle. ``from_uri`` is provided for
    application composition and marks the client as owned by this unit.
    """

    def __init__(self, client, database_name: str, *, owns_client: bool = False) -> None:
        if not database_name:
            raise ValueError("database_name is required")
        self._client = client
        self._owns_client = owns_client
        self.database_name = database_name
        self._database = client.get_database(
            database_name,
            codec_options=CodecOptions(tz_aware=True, tzinfo=timezone.utc),
        )
        self._counters = self._database["counters"]
        self.raw_records = _MongoRawRecordRepository(self._database["raw_records"])
        self.transactions = _MongoTransactionRepository(self._database["transactions"])
        self.classifications = _MongoClassificationRepository(
            self._database["classifications"], self._counters
        )
        self.outbox = _MongoOutboxRepository(self._database["outbox"])
        self.oauth_states = _MongoOAuthStateRepository(self._database["oauth_states"])
        self.audit = _MongoAuditRepository(self._database["audit_events"], self._counters)
        self.uploads = _MongoUploadRepository(self._database["uploads"])
        self.pipeline_contexts = _MongoPipelineContextRepository(
            self._database["pipeline_contexts"]
        )
        self.sync_runs = _MongoSyncRunRepository(self._database["sync_runs"])
        self.reconciliation_runs = _MongoReconciliationRunRepository(
            self._database["reconciliation_runs"]
        )
        self.demo_grants = _MongoDemoGrantRepository(self._database["demo_grants"])
        self.qbo_connection = _MongoQboConnectionRepository(
            self._database["qbo_connections"]
        )
        self.execution_leases = _MongoExecutionLeaseRepository(
            self._database["execution_leases"]
        )
        self.demo_reset = _MongoDemoResetRepository(self._database)

    @classmethod
    def from_uri(cls, uri: str, database_name: str) -> "MongoUnitOfWork":
        from pymongo import AsyncMongoClient

        client = AsyncMongoClient(
            uri,
            serverSelectionTimeoutMS=5_000,
            tz_aware=True,
        )
        return cls(client, database_name, owns_client=True)

    async def create_indexes(self) -> None:
        await self._database["raw_records"].create_index(
            [("raw_row_sha256", ASCENDING)],
            name="raw_row_sha256",
        )
        await self._database["raw_records"].create_index(
            [
                ("source_file_sha256", ASCENDING),
                ("source_sheet", ASCENDING),
                ("source_row_number", ASCENDING),
            ],
            name="source_lineage",
        )
        await self._database["transactions"].create_index(
            [("bank_transaction_id", ASCENDING)],
            unique=True,
            name="bank_transaction_id",
        )
        await self._database["transactions"].create_index(
            [("raw_record_id", ASCENDING)], name="raw_record_id"
        )
        await self._database["transactions"].create_index(
            [("transaction_date", ASCENDING)], name="transaction_date"
        )
        await self._database["classifications"].create_index(
            [("transaction_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
            name="transaction_version_unique",
        )
        await self._database["outbox"].create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="idempotency_key_unique",
        )
        await self._database["outbox"].create_index(
            [("status", ASCENDING), ("next_attempt_at", ASCENDING)],
            name="status_next_attempt",
        )
        await self._database["oauth_states"].create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="expires_at_ttl",
        )
        await self._database["audit_events"].create_index(
            [("sequence", ASCENDING)], unique=True, name="sequence_unique"
        )
        await self._database["uploads"].create_index(
            [("id", ASCENDING)], unique=True, name="id_unique"
        )
        await self._database["pipeline_contexts"].create_index(
            [("upload_id", ASCENDING)], unique=True, name="upload_id_unique"
        )
        await self._database["pipeline_contexts"].create_index(
            [("transaction_ids", ASCENDING)], unique=True, name="transaction_ids"
        )
        await self._database["sync_runs"].create_index(
            [("id", ASCENDING)], unique=True, name="id_unique"
        )
        await self._database["reconciliation_runs"].create_index(
            [("id", ASCENDING)], unique=True, name="id_unique"
        )
        await self._database["demo_grants"].create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="expires_at_ttl",
        )
        await self._database["execution_leases"].create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="expires_at_ttl",
        )
        await self._database["qbo_connections"].create_index(
            [("singleton", ASCENDING)], unique=True, name="singleton_unique"
        )
        await self._database["reset_runs"].create_index(
            [("id", ASCENDING)], unique=True, name="id_unique"
        )

    async def index_information(self) -> dict[str, dict[str, dict[str, Any]]]:
        names = (
            "raw_records",
            "transactions",
            "classifications",
            "outbox",
            "oauth_states",
            "audit_events",
            "uploads",
            "pipeline_contexts",
            "sync_runs",
            "reconciliation_runs",
            "demo_grants",
            "qbo_connections",
            "execution_leases",
            "reset_runs",
        )
        return {
            name: await self._database[name].index_information() for name in names
        }

    async def ping(self) -> bool:
        result = await self._database.command({"ping": 1})
        return result.get("ok") == 1

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()
            self._owns_client = False

    async def __aenter__(self) -> "MongoUnitOfWork":
        return self

    async def __aexit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> None:
        return None
