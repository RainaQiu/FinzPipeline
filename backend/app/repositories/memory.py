"""Async, concurrency-safe in-memory repositories used by tests and local flows."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256

from app.domain.accounting import OutboxItem, OutboxStatus
from app.domain.classification import ClassificationDecision
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
from app.domain.transactions import NormalizedTransaction, RawRecord
from app.repositories.protocols import (
    AuditEvent,
    ImmutableRecordError,
    InvalidStateTransitionError,
    OAuthState,
    OAuthStateExpiredError,
    TransactionContextConflictError,
)


class _InMemoryRawRecordRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._records: dict[str, RawRecord] = {}

    async def add(self, record: RawRecord) -> RawRecord:
        async with self._lock:
            existing = self._records.get(record.id)
            if existing is None:
                self._records[record.id] = record
                return record
            if replace(existing, ingested_at=record.ingested_at) != record:
                raise ImmutableRecordError(f"raw record {record.id!r} is immutable")
            return existing

    async def get(self, record_id: str) -> RawRecord | None:
        async with self._lock:
            return self._records.get(record_id)

    async def list(self, *, offset: int = 0, limit: int | None = None) -> tuple[RawRecord, ...]:
        if offset < 0 or limit is not None and limit < 0:
            raise ValueError("offset and limit must not be negative")
        async with self._lock:
            records = tuple(self._records.values())
        return records[offset:] if limit is None else records[offset : offset + limit]


class _InMemoryClassificationRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._by_id: dict[str, ClassificationDecision] = {}
        self._by_transaction: dict[str, list[ClassificationDecision]] = {}

    async def append(self, decision: ClassificationDecision) -> ClassificationDecision:
        async with self._lock:
            existing = self._by_id.get(decision.id)
            if existing is not None:
                if existing == decision:
                    return existing
                raise ImmutableRecordError(
                    f"classification decision {decision.id!r} is append-only"
                )
            history = self._by_transaction.setdefault(decision.transaction_id, [])
            stored = replace(decision, version=len(history) + 1)
            self._by_id[stored.id] = stored
            history.append(stored)
            return stored

    async def latest(self, transaction_id: str) -> ClassificationDecision | None:
        async with self._lock:
            history = self._by_transaction.get(transaction_id, ())
            return history[-1] if history else None

    async def history(
        self, transaction_id: str, *, offset: int = 0, limit: int | None = None
    ) -> tuple[ClassificationDecision, ...]:
        if offset < 0 or limit is not None and limit < 0:
            raise ValueError("offset and limit must not be negative")
        async with self._lock:
            decisions = tuple(self._by_transaction.get(transaction_id, ()))
        return decisions[offset:] if limit is None else decisions[offset : offset + limit]


class _InMemoryTransactionRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._transactions: dict[str, NormalizedTransaction] = {}

    async def add(self, transaction: NormalizedTransaction) -> NormalizedTransaction:
        async with self._lock:
            existing = self._transactions.get(transaction.id)
            if existing is None:
                self._transactions[transaction.id] = transaction
                return transaction
            if existing != transaction:
                raise ImmutableRecordError(f"transaction {transaction.id!r} is immutable")
            return existing

    async def get(self, transaction_id: str) -> NormalizedTransaction | None:
        async with self._lock:
            return self._transactions.get(transaction_id)

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
        if offset < 0 or limit is not None and limit < 0:
            raise ValueError("offset and limit must not be negative")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        async with self._lock:
            values = tuple(self._transactions.values())
        filtered = tuple(
            transaction
            for transaction in values
            if (raw_record_id is None or transaction.raw_record_id == raw_record_id)
            and (bank_transaction_id is None or transaction.bank_transaction_id == bank_transaction_id)
            and (start_date is None or transaction.transaction_date >= start_date)
            and (end_date is None or transaction.transaction_date <= end_date)
        )
        return filtered[offset:] if limit is None else filtered[offset : offset + limit]


class _InMemoryOutboxRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._by_id: dict[str, OutboxItem] = {}
        self._by_key: dict[str, str] = {}

    @staticmethod
    def _key(item: OutboxItem) -> str:
        return item.idempotency_key or item.id

    async def add(self, item: OutboxItem) -> OutboxItem:
        async with self._lock:
            key = self._key(item)
            existing_id = self._by_key.get(key)
            if existing_id is not None:
                return self._by_id[existing_id]
            by_id = self._by_id.get(item.id)
            if by_id is not None:
                if by_id != item:
                    raise ImmutableRecordError(f"outbox item {item.id!r} is immutable")
                return by_id
            stored = item if item.idempotency_key else replace(item, idempotency_key=key)
            self._by_id[stored.id] = stored
            self._by_key[key] = stored.id
            return stored

    async def get(self, item_id: str) -> OutboxItem | None:
        async with self._lock:
            return self._by_id.get(item_id)

    async def claim_pending(self, *, limit: int = 1) -> tuple[OutboxItem, ...]:
        if limit < 0:
            raise ValueError("limit must not be negative")
        claimed: list[OutboxItem] = []
        async with self._lock:
            for item_id, item in self._by_id.items():
                if len(claimed) == limit:
                    break
                if item.status is OutboxStatus.PENDING:
                    updated = replace(
                        item,
                        status=OutboxStatus.PROCESSING,
                        attempt_count=item.attempt_count + 1,
                        updated_at=datetime.now(timezone.utc),
                    )
                    self._by_id[item_id] = updated
                    claimed.append(updated)
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
        async with self._lock:
            item = self._by_id.get(item_id)
            if item is None:
                raise KeyError(item_id)
            allowed = {
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
            if status not in allowed[item.status]:
                raise InvalidStateTransitionError(f"cannot transition {item.status} to {status}")
            updated = replace(
                item,
                status=status,
                updated_at=updated_at or datetime.now(timezone.utc),
                next_attempt_at=next_attempt_at,
                last_error_code=last_error_code,
                qbo_entity_id=qbo_entity_id if qbo_entity_id is not None else item.qbo_entity_id,
                sync_token=sync_token if sync_token is not None else item.sync_token,
            )
            self._by_id[item_id] = updated
            return updated


class _InMemoryOAuthStateRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._states: dict[str, OAuthState] = {}

    @staticmethod
    def _hash(state: str) -> str:
        return sha256(state.encode("utf-8")).hexdigest()

    async def put(self, state: str, *, expires_at: datetime) -> OAuthState:
        state_hash = self._hash(state)
        saved = OAuthState(state_hash=state_hash, expires_at=expires_at)
        async with self._lock:
            self._states[state_hash] = saved
        return saved

    async def consume(self, state: str, *, now: datetime | None = None) -> OAuthState | None:
        state_hash = self._hash(state)
        current_time = now or datetime.now(timezone.utc)
        async with self._lock:
            saved = self._states.pop(state_hash, None)
            if saved is None:
                return None
            if saved.expires_at <= current_time:
                raise OAuthStateExpiredError("OAuth state has expired")
            return saved


class _InMemoryAuditRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> AuditEvent:
        async with self._lock:
            stored = replace(event, sequence=len(self._events) + 1)
            self._events.append(stored)
            return stored

    async def list(self, *, offset: int = 0, limit: int | None = None) -> tuple[AuditEvent, ...]:
        if offset < 0 or limit is not None and limit < 0:
            raise ValueError("offset and limit must not be negative")
        async with self._lock:
            events = tuple(self._events)
        return events[offset:] if limit is None else events[offset : offset + limit]


class _InMemoryUploadRepository:
    _ALLOWED = {
        "uploaded": {"processing"},
        "failed": {"processing"},
        "processing": {"processing", "completed", "failed"},
        "completed": set(),
    }

    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._records: dict[str, UploadRecord] = {}

    async def add(self, upload: UploadRecord) -> UploadRecord:
        async with self._lock:
            existing = self._records.get(upload.id)
            if existing is None:
                self._records[upload.id] = upload
                return upload
            if existing != upload:
                raise ImmutableRecordError(f"upload {upload.id!r} is immutable")
            return existing

    async def get(self, upload_id: str) -> UploadRecord | None:
        async with self._lock:
            return self._records.get(upload_id)

    async def transition_status(
        self,
        upload: UploadRecord,
        *,
        expected_status: str,
        expected_token: str | None = None,
    ) -> UploadRecord:
        async with self._lock:
            existing = self._records.get(upload.id)
            if existing is None:
                raise KeyError(upload.id)
            if (
                existing.id,
                existing.original_filename,
                existing.media_type,
                existing.sha256,
                existing.data,
                existing.created_at,
            ) != (
                upload.id,
                upload.original_filename,
                upload.media_type,
                upload.sha256,
                upload.data,
                upload.created_at,
            ):
                raise ImmutableRecordError(
                    f"upload {upload.id!r} source fields are immutable"
                )
            if (
                existing.status != expected_status
                or existing.processing_token != expected_token
                or upload.status not in self._ALLOWED.get(expected_status, set())
                or (
                    expected_status == "processing"
                    and upload.status == "processing"
                    and upload.processing_token == expected_token
                )
            ):
                raise InvalidStateTransitionError(
                    f"upload {upload.id!r} cannot transition "
                    f"from {existing.status!r} to {upload.status!r}"
                )
            self._records[upload.id] = upload
            return upload


class _InMemoryPipelineContextRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._records: dict[str, PipelineContext] = {}

    async def upsert(self, context: PipelineContext) -> PipelineContext:
        async with self._lock:
            transaction_ids = frozenset(context.transaction_statuses)
            for existing in self._records.values():
                if (
                    existing.upload_id != context.upload_id
                    and transaction_ids
                    & frozenset(existing.transaction_statuses)
                ):
                    raise TransactionContextConflictError(
                        "transaction already belongs to upload "
                        f"{existing.upload_id!r}"
                    )
            self._records[context.upload_id] = context
            return context

    async def get(self, upload_id: str) -> PipelineContext | None:
        async with self._lock:
            return self._records.get(upload_id)

    async def get_for_transaction(
        self, transaction_id: str
    ) -> PipelineContext | None:
        async with self._lock:
            return next(
                (
                    context
                    for context in self._records.values()
                    if transaction_id in context.transaction_statuses
                ),
                None,
            )


class _InMemorySyncRunRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._records: dict[str, SyncRunRecord] = {}

    async def add(self, run: SyncRunRecord) -> SyncRunRecord:
        async with self._lock:
            existing = self._records.get(run.id)
            if existing is None:
                self._records[run.id] = run
                return run
            if existing != run:
                raise ImmutableRecordError(f"sync run {run.id!r} is immutable")
            return existing

    async def get(self, run_id: str) -> SyncRunRecord | None:
        async with self._lock:
            return self._records.get(run_id)


class _InMemoryReconciliationRunRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._records: dict[str, ReconciliationRunRecord] = {}

    async def add(self, run: ReconciliationRunRecord) -> ReconciliationRunRecord:
        async with self._lock:
            existing = self._records.get(run.id)
            if existing is None:
                self._records[run.id] = run
                return run
            if existing != run:
                raise ImmutableRecordError(
                    f"reconciliation run {run.id!r} is immutable"
                )
            return existing

    async def get(self, run_id: str) -> ReconciliationRunRecord | None:
        async with self._lock:
            return self._records.get(run_id)


class _InMemoryDemoGrantRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._records: dict[str, DemoGrant] = {}

    async def issue(self, grant: DemoGrant) -> DemoGrant:
        async with self._lock:
            self._records[grant.token_hash] = grant
            return grant

    async def consume_valid(
        self, token_hash: str, *, now: datetime
    ) -> DemoGrant | None:
        async with self._lock:
            grant = self._records.pop(token_hash, None)
            if grant is None or grant.expires_at <= now:
                return None
            return grant


class _InMemoryQboConnectionRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._connection: QboConnection | None = None

    async def upsert(self, connection: QboConnection) -> QboConnection:
        async with self._lock:
            self._connection = connection
            return connection

    async def get(self) -> QboConnection | None:
        async with self._lock:
            return self._connection


class _InMemoryExecutionLeaseRepository:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._active: ExecutionLease | None = None

    async def acquire(self, lease: ExecutionLease, *, now: datetime) -> bool:
        if not (lease.acquired_at <= now < lease.expires_at):
            return False
        async with self._lock:
            if self._active is not None and self._active.expires_at > now:
                return False
            self._active = lease
            return True

    async def release(self, lease_id: str) -> None:
        async with self._lock:
            if self._active is not None and self._active.id == lease_id:
                self._active = None


class _InMemoryDemoResetRepository:
    def __init__(
        self,
        lock: asyncio.Lock,
        *,
        raw_records: _InMemoryRawRecordRepository,
        transactions: _InMemoryTransactionRepository,
        classifications: _InMemoryClassificationRepository,
        outbox: _InMemoryOutboxRepository,
        oauth_states: _InMemoryOAuthStateRepository,
        audit: _InMemoryAuditRepository,
        uploads: _InMemoryUploadRepository,
        pipeline_contexts: _InMemoryPipelineContextRepository,
        sync_runs: _InMemorySyncRunRepository,
        reconciliation_runs: _InMemoryReconciliationRunRepository,
        demo_grants: _InMemoryDemoGrantRepository,
        execution_leases: _InMemoryExecutionLeaseRepository,
    ) -> None:
        self._lock = lock
        self._records: dict[str, ResetRun] = {}
        self._raw_records = raw_records
        self._transactions = transactions
        self._classifications = classifications
        self._outbox = outbox
        self._oauth_states = oauth_states
        self._audit = audit
        self._uploads = uploads
        self._pipeline_contexts = pipeline_contexts
        self._sync_runs = sync_runs
        self._reconciliation_runs = reconciliation_runs
        self._demo_grants = demo_grants
        self._execution_leases = execution_leases

    async def add(self, run: ResetRun) -> ResetRun:
        async with self._lock:
            existing = self._records.get(run.id)
            if existing is None:
                self._records[run.id] = run
                return run
            if existing != run:
                raise ImmutableRecordError(f"reset run {run.id!r} is immutable")
            return existing

    async def clear_shared_workspace(self) -> None:
        async with self._lock:
            self._uploads._records.clear()
            self._pipeline_contexts._records.clear()
            self._sync_runs._records.clear()
            self._reconciliation_runs._records.clear()
            self._demo_grants._records.clear()
            self._execution_leases._active = None
            self._records.clear()
            async with self._raw_records._lock:
                self._raw_records._records.clear()
            async with self._transactions._lock:
                self._transactions._transactions.clear()
            async with self._classifications._lock:
                self._classifications._by_id.clear()
                self._classifications._by_transaction.clear()
            async with self._outbox._lock:
                self._outbox._by_id.clear()
                self._outbox._by_key.clear()
            async with self._oauth_states._lock:
                self._oauth_states._states.clear()
            async with self._audit._lock:
                self._audit._events.clear()


class InMemoryUnitOfWork:
    """A process-local unit of work with shared locks for atomic operations."""

    def __init__(self) -> None:
        self._raw_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()
        self._classification_lock = asyncio.Lock()
        self._outbox_lock = asyncio.Lock()
        self._oauth_state_lock = asyncio.Lock()
        self._audit_lock = asyncio.Lock()
        self._demo_lock = asyncio.Lock()
        self.raw_records = _InMemoryRawRecordRepository(self._raw_lock)
        self.transactions = _InMemoryTransactionRepository(self._transaction_lock)
        self.classifications = _InMemoryClassificationRepository(self._classification_lock)
        self.outbox = _InMemoryOutboxRepository(self._outbox_lock)
        self.oauth_states = _InMemoryOAuthStateRepository(self._oauth_state_lock)
        self.audit = _InMemoryAuditRepository(self._audit_lock)
        self.uploads = _InMemoryUploadRepository(self._demo_lock)
        self.pipeline_contexts = _InMemoryPipelineContextRepository(self._demo_lock)
        self.sync_runs = _InMemorySyncRunRepository(self._demo_lock)
        self.reconciliation_runs = _InMemoryReconciliationRunRepository(
            self._demo_lock
        )
        self.demo_grants = _InMemoryDemoGrantRepository(self._demo_lock)
        self.qbo_connection = _InMemoryQboConnectionRepository(self._demo_lock)
        self.execution_leases = _InMemoryExecutionLeaseRepository(self._demo_lock)
        self.demo_reset = _InMemoryDemoResetRepository(
            self._demo_lock,
            raw_records=self.raw_records,
            transactions=self.transactions,
            classifications=self.classifications,
            outbox=self.outbox,
            oauth_states=self.oauth_states,
            audit=self.audit,
            uploads=self.uploads,
            pipeline_contexts=self.pipeline_contexts,
            sync_runs=self.sync_runs,
            reconciliation_runs=self.reconciliation_runs,
            demo_grants=self.demo_grants,
            execution_leases=self.execution_leases,
        )

    async def __aenter__(self) -> "InMemoryUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None
