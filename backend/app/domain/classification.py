from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.accounts import parse_account
from app.domain.transactions import _require_int


class TransactionType(StrEnum):
    REVENUE = "revenue"
    COGS = "cogs"
    OPERATING_EXPENSE = "operating_expense"
    REFUND = "refund"
    TRANSFER = "transfer"
    OWNER_ACTIVITY = "owner_activity"
    FIXED_ASSET = "fixed_asset"


class DecisionSource(StrEnum):
    HARD_RULE = "hard_rule"
    LEARNED_RULE = "learned_rule"
    MERCHANT_RULE = "merchant_rule"
    AI = "ai"
    HUMAN = "human"


class ApprovalStatus(StrEnum):
    SUGGESTED = "suggested"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    id: str
    transaction_id: str
    account_number: str
    transaction_type: TransactionType
    source: DecisionSource
    confidence_basis_points: int
    approval_status: ApprovalStatus
    needs_review: bool
    explanation: str
    created_at: datetime
    version: int = 1
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        parse_account(self.account_number)
        _require_int(self.confidence_basis_points, "confidence_basis_points")
        _require_int(self.version, "version")
        if not 0 <= self.confidence_basis_points <= 10000:
            raise ValueError("confidence_basis_points must be between 0 and 10000")
        if self.version < 1:
            raise ValueError("version must be positive")
        if self.source is DecisionSource.AI and (
            self.approval_status is not ApprovalStatus.SUGGESTED or not self.needs_review
        ):
            raise ValueError("AI decisions must be suggested and require review")
