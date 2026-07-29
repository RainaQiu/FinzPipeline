"""Provider-neutral, non-authoritative AI classification contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from app.domain.accounts import AccountType
from app.domain.transactions import Direction, NormalizedTransaction


@dataclass(frozen=True, slots=True)
class AllowedAccount:
    number: str
    account_type: AccountType


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    transaction_id: str
    description: str
    amount_minor: int
    direction: Direction
    transaction_date: date
    bank_account_number: str

    @classmethod
    def from_transaction(cls, transaction: NormalizedTransaction) -> "ClassificationInput":
        return cls(
            transaction_id=transaction.id,
            description=transaction.description_normalized,
            amount_minor=transaction.amount_minor,
            direction=transaction.direction,
            transaction_date=transaction.transaction_date,
            bank_account_number=transaction.bank_account_number,
        )


@dataclass(frozen=True, slots=True)
class ClassificationProposal:
    transaction_type: str
    counterparty: str | None
    account_number: str
    confidence: float
    needs_review: bool
    evidence: tuple[str, ...]
    # These fields deliberately exist only so post-validation can reject a
    # provider attempting to take ownership of bank-controlled values.
    amount_minor: int | None = None
    transaction_date: date | None = None
    bank_transaction_id: str | None = None
    transaction_id: str | None = None


class ClassificationProvider(Protocol):
    async def classify(
        self, transaction: ClassificationInput, allowed_accounts: Sequence[AllowedAccount]
    ) -> ClassificationProposal: ...


class DisabledClassificationProvider:
    """Explicit no-provider implementation; it never performs I/O."""

    async def classify(
        self, transaction: ClassificationInput, allowed_accounts: Sequence[AllowedAccount]
    ) -> ClassificationProposal:
        return ClassificationProposal(
            transaction_type="unknown",
            counterparty=None,
            account_number="",
            confidence=0.0,
            needs_review=True,
            evidence=("AI classification is disabled.",),
        )
