"""Immutable records for the persistent public-cloud demonstration workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from app.domain.transactions import _freeze_value, _require_int


def _canonical_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    utc_value = value.astimezone(timezone.utc)
    return utc_value.replace(microsecond=utc_value.microsecond // 1000 * 1000)


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


@dataclass(frozen=True, slots=True)
class UploadRecord:
    id: str
    original_filename: str
    media_type: str
    sha256: str
    data: bytes
    created_at: datetime
    status: str = "uploaded"
    processing_started_at: datetime | None = None
    processing_token: str | None = field(default=None, repr=False)
    mapping_version: int = 0
    row_count: int = 0
    completed_at: datetime | None = None
    error_summary: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise TypeError("data must be immutable bytes")
        _require_int(self.mapping_version, "mapping_version")
        _require_int(self.row_count, "row_count")
        object.__setattr__(
            self, "created_at", _canonical_datetime(self.created_at, "created_at")
        )
        if self.processing_started_at is not None:
            object.__setattr__(
                self,
                "processing_started_at",
                _canonical_datetime(
                    self.processing_started_at, "processing_started_at"
                ),
            )
        if self.status == "processing":
            if self.processing_started_at is None:
                raise ValueError(
                    "processing_started_at is required while processing"
                )
            if not isinstance(self.processing_token, str):
                raise TypeError("processing_token must be a string")
            if not self.processing_token.strip():
                raise ValueError(
                    "processing_token is required while processing"
                )
        elif (
            self.processing_started_at is not None
            or self.processing_token is not None
        ):
            raise ValueError(
                "processing claim fields are only allowed while processing"
            )
        if self.completed_at is not None:
            object.__setattr__(
                self,
                "completed_at",
                _canonical_datetime(self.completed_at, "completed_at"),
            )
        if not all(isinstance(error, str) for error in self.error_summary):
            raise TypeError("error_summary items must be strings")
        object.__setattr__(self, "error_summary", tuple(self.error_summary))


@dataclass(frozen=True, slots=True)
class PipelineContext:
    id: str
    upload_id: str
    status: str
    transaction_statuses: Mapping[str, object]
    transfer_pairs: Mapping[str, object]
    created_at: datetime
    updated_at: datetime
    counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "created_at", _canonical_datetime(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", _canonical_datetime(self.updated_at, "updated_at")
        )
        object.__setattr__(self, "transaction_statuses", _freeze_mapping(self.transaction_statuses))
        object.__setattr__(self, "transfer_pairs", _freeze_mapping(self.transfer_pairs))
        validated_counts: dict[str, int] = {}
        for key, value in self.counts.items():
            if not isinstance(key, str):
                raise TypeError("counts keys must be strings")
            _require_int(value, f"counts[{key!r}]")
            if value < 0:
                raise ValueError("counts values must not be negative")
            validated_counts[key] = value
        object.__setattr__(self, "counts", MappingProxyType(validated_counts))


@dataclass(frozen=True, slots=True)
class SyncRunRecord:
    id: str
    status: str
    item_views: Mapping[str, object]
    started_at: datetime
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "started_at", _canonical_datetime(self.started_at, "started_at")
        )
        if self.completed_at is not None:
            object.__setattr__(
                self,
                "completed_at",
                _canonical_datetime(self.completed_at, "completed_at"),
            )
        object.__setattr__(self, "item_views", _freeze_mapping(self.item_views))


@dataclass(frozen=True, slots=True)
class ReconciliationRunRecord:
    id: str
    status: str
    account_views: Mapping[str, object]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "created_at", _canonical_datetime(self.created_at, "created_at")
        )
        object.__setattr__(self, "account_views", _freeze_mapping(self.account_views))


@dataclass(frozen=True, slots=True)
class DemoGrant:
    token_hash: str
    expires_at: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "expires_at", _canonical_datetime(self.expires_at, "expires_at")
        )
        object.__setattr__(
            self, "created_at", _canonical_datetime(self.created_at, "created_at")
        )


@dataclass(frozen=True, slots=True)
class QboConnection:
    realm_id: str
    company_name: str
    encrypted_access_token: str = field(repr=False)
    encrypted_refresh_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_expires_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "access_expires_at",
            _canonical_datetime(self.access_expires_at, "access_expires_at"),
        )
        object.__setattr__(
            self,
            "refresh_expires_at",
            _canonical_datetime(self.refresh_expires_at, "refresh_expires_at"),
        )
        object.__setattr__(
            self, "updated_at", _canonical_datetime(self.updated_at, "updated_at")
        )


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    id: str
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "acquired_at",
            _canonical_datetime(self.acquired_at, "acquired_at"),
        )
        object.__setattr__(
            self, "expires_at", _canonical_datetime(self.expires_at, "expires_at")
        )
        if self.expires_at <= self.acquired_at:
            raise ValueError("expires_at must be after acquired_at")


@dataclass(frozen=True, slots=True)
class ResetRun:
    id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "started_at", _canonical_datetime(self.started_at, "started_at")
        )
        if self.completed_at is not None:
            object.__setattr__(
                self,
                "completed_at",
                _canonical_datetime(self.completed_at, "completed_at"),
            )
