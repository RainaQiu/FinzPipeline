"""Repository contracts independent of the storage engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Mapping, Protocol

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
from app.domain.transactions import NormalizedTransaction, RawRecord, _freeze_value


class ImmutableRecordError(ValueError):
    """Raised when an insert-only record ID is reused with different content."""


class InvalidStateTransitionError(ValueError):
    """Raised when an outbox item is moved through an invalid lifecycle edge."""


class OAuthStateExpiredError(ValueError):
    """Raised when a one-time OAuth state is presented after its expiry."""


@dataclass(frozen=True, slots=True)
class OAuthState:
    """The persisted OAuth state metadata; the raw state is never retained."""

    state_hash: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable audit entry with an append-assigned stable sequence."""

    event_type: str
    payload: Mapping[str, object]
    occurred_at: datetime
    sequence: int = 0

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")
        object.__setattr__(
            self,
            "payload",
            MappingProxyType({key: _freeze_value(value) for key, value in self.payload.items()}),
        )


class RawRecordRepository(Protocol):
    async def add(self, record: RawRecord) -> RawRecord: ...

    async def get(self, record_id: str) -> RawRecord | None: ...

    async def list(self, *, offset: int = 0, limit: int | None = None) -> tuple[RawRecord, ...]: ...


class ClassificationRepository(Protocol):
    async def append(self, decision: ClassificationDecision) -> ClassificationDecision: ...

    async def latest(self, transaction_id: str) -> ClassificationDecision | None: ...

    async def history(
        self, transaction_id: str, *, offset: int = 0, limit: int | None = None
    ) -> tuple[ClassificationDecision, ...]: ...


class TransactionRepository(Protocol):
    async def add(self, transaction: NormalizedTransaction) -> NormalizedTransaction: ...

    async def get(self, transaction_id: str) -> NormalizedTransaction | None: ...

    async def list(
        self,
        *,
        raw_record_id: str | None = None,
        bank_transaction_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[NormalizedTransaction, ...]: ...


class OutboxRepository(Protocol):
    async def add(self, item: OutboxItem) -> OutboxItem: ...

    async def get(self, item_id: str) -> OutboxItem | None: ...

    async def claim_pending(self, *, limit: int = 1) -> tuple[OutboxItem, ...]: ...

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
    ) -> OutboxItem: ...


class OAuthStateRepository(Protocol):
    async def put(self, state: str, *, expires_at: datetime) -> OAuthState: ...

    async def consume(
        self, state: str, *, now: datetime | None = None
    ) -> OAuthState | None: ...


class AuditRepository(Protocol):
    async def append(self, event: AuditEvent) -> AuditEvent: ...

    async def list(self, *, offset: int = 0, limit: int | None = None) -> tuple[AuditEvent, ...]: ...


class UploadRepository(Protocol):
    async def add(self, upload: UploadRecord) -> UploadRecord: ...

    async def get(self, upload_id: str) -> UploadRecord | None: ...

    async def update_status(self, upload: UploadRecord) -> UploadRecord: ...


class PipelineContextRepository(Protocol):
    async def upsert(self, context: PipelineContext) -> PipelineContext: ...

    async def get(self, upload_id: str) -> PipelineContext | None: ...

    async def get_for_transaction(
        self, transaction_id: str
    ) -> PipelineContext | None: ...


class SyncRunRepository(Protocol):
    async def add(self, run: SyncRunRecord) -> SyncRunRecord: ...

    async def get(self, run_id: str) -> SyncRunRecord | None: ...


class ReconciliationRunRepository(Protocol):
    async def add(self, run: ReconciliationRunRecord) -> ReconciliationRunRecord: ...

    async def get(self, run_id: str) -> ReconciliationRunRecord | None: ...


class DemoGrantRepository(Protocol):
    async def issue(self, grant: DemoGrant) -> DemoGrant: ...

    async def consume_valid(self, token_hash: str, *, now: datetime) -> DemoGrant | None: ...


class QboConnectionRepository(Protocol):
    async def upsert(self, connection: QboConnection) -> QboConnection: ...

    async def get(self) -> QboConnection | None: ...


class ExecutionLeaseRepository(Protocol):
    async def acquire(self, lease: ExecutionLease, *, now: datetime) -> bool: ...

    async def release(self, lease_id: str) -> None: ...


class DemoResetRepository(Protocol):
    async def add(self, run: ResetRun) -> ResetRun: ...

    async def clear_shared_workspace(self) -> None: ...


class UnitOfWork(Protocol):
    raw_records: RawRecordRepository
    transactions: TransactionRepository
    classifications: ClassificationRepository
    outbox: OutboxRepository
    audit: AuditRepository
    oauth_states: OAuthStateRepository
    uploads: UploadRepository
    pipeline_contexts: PipelineContextRepository
    sync_runs: SyncRunRepository
    reconciliation_runs: ReconciliationRunRepository
    demo_grants: DemoGrantRepository
    qbo_connection: QboConnectionRepository
    execution_leases: ExecutionLeaseRepository
    demo_reset: DemoResetRepository

    async def __aenter__(self) -> "UnitOfWork": ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
