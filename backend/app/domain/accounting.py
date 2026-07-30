from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from app.domain.accounts import parse_account
from app.domain.transactions import _freeze_value, _require_int


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    PERMANENT_FAILED = "permanent_failed"


class ReconciliationStatus(StrEnum):
    MATCHED = "matched"
    DIFFERENCES = "differences"


@dataclass(frozen=True, slots=True)
class LedgerLine:
    id: str
    transaction_id: str
    classification_decision_id: str
    account_number: str
    amount_minor: int
    transaction_date: date

    def __post_init__(self) -> None:
        parse_account(self.account_number)
        _require_int(self.amount_minor, "amount_minor")


@dataclass(frozen=True, slots=True)
class PnlLine:
    """One immutable account drill-down in a cash-basis P&L."""

    account_number: str
    account_name: str
    total_minor: int
    transaction_count: int
    transaction_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        parse_account(self.account_number)
        _require_int(self.total_minor, "total_minor")
        _require_int(self.transaction_count, "transaction_count")
        if self.transaction_count < 0:
            raise ValueError("transaction_count cannot be negative")
        if self.transaction_count != len(self.transaction_ids):
            raise ValueError("transaction_count must equal transaction_ids length")

    @property
    def count(self) -> int:
        """Short report-facing alias for the transaction drill-down count."""
        return self.transaction_count

    @property
    def total(self) -> int:
        """Short report-facing alias for the displayed account amount in cents."""
        return self.total_minor


@dataclass(frozen=True, slots=True)
class ProfitAndLoss:
    """Cash-basis P&L totals and their account-level audit trail."""

    start_date: date
    end_date: date
    revenue_lines: tuple[PnlLine, ...]
    cogs_lines: tuple[PnlLine, ...]
    operating_expense_lines: tuple[PnlLine, ...]
    total_revenue_minor: int
    total_cogs_minor: int
    gross_profit_minor: int
    total_operating_expenses_minor: int
    net_profit_minor: int

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        for field_name in (
            "total_revenue_minor",
            "total_cogs_minor",
            "gross_profit_minor",
            "total_operating_expenses_minor",
            "net_profit_minor",
        ):
            _require_int(getattr(self, field_name), field_name)

    @property
    def account_totals(self) -> Mapping[str, int]:
        """Return immutable displayed P&L totals keyed by account number."""
        return MappingProxyType(
            {
                line.account_number: line.total_minor
                for line in (
                    *self.revenue_lines,
                    *self.cogs_lines,
                    *self.operating_expense_lines,
                )
            }
        )


@dataclass(frozen=True, slots=True)
class QboProfitAndLoss:
    """Normalized, immutable QBO cash-basis P&L snapshot."""

    account_totals: Mapping[str, int]
    raw_snapshot: Mapping[str, object]
    net_profit_minor: int | None = None
    no_report_data: bool = False
    source: str = "qbo_sandbox"

    def __post_init__(self) -> None:
        for account_number, amount_minor in self.account_totals.items():
            parse_account(account_number)
            _require_int(amount_minor, "account_totals amount")
        if self.net_profit_minor is not None:
            _require_int(self.net_profit_minor, "net_profit_minor")
        object.__setattr__(
            self,
            "account_totals",
            MappingProxyType(dict(self.account_totals)),
        )
        object.__setattr__(
            self,
            "raw_snapshot",
            MappingProxyType(
                {key: _freeze_value(value) for key, value in self.raw_snapshot.items()}
            ),
        )


@dataclass(frozen=True, slots=True)
class ReconciliationLine:
    account_number: str
    internal_minor: int
    qbo_minor: int
    difference_minor: int
    status: ReconciliationStatus
    diagnostic_candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.account_number != "net_profit":
            parse_account(self.account_number)
        _require_int(self.internal_minor, "internal_minor")
        _require_int(self.qbo_minor, "qbo_minor")
        _require_int(self.difference_minor, "difference_minor")


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    lines: tuple[ReconciliationLine, ...]
    status: ReconciliationStatus


@dataclass(frozen=True, slots=True)
class OutboxItem:
    id: str
    realm_id: str
    transaction_id: str
    classification_version: int
    payload_kind: str
    payload: Mapping[str, object]
    status: OutboxStatus
    created_at: datetime
    updated_at: datetime | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    idempotency_key: str = ""
    classification_decision_id: str | None = None
    qbo_entity_id: str | None = None
    sync_token: str | None = None

    def __post_init__(self) -> None:
        _require_int(self.classification_version, "classification_version")
        _require_int(self.attempt_count, "attempt_count")
        if self.classification_version < 1:
            raise ValueError("classification_version must be positive")
        if self.attempt_count < 0:
            raise ValueError("attempt_count cannot be negative")
        object.__setattr__(
            self,
            "payload",
            MappingProxyType(
                {key: _freeze_value(value) for key, value in self.payload.items()}
            ),
        )
