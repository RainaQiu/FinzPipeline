"""Provider-neutral, non-authoritative AI classification contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

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


class ClassificationProposal(BaseModel):
    """The complete and deliberately narrow authority granted to an AI provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_type: str
    account_number: str
    explanation: str = Field(min_length=1, max_length=500)
    confidence_basis_points: int = Field(ge=0, le=10000)


class ClassificationProvider(Protocol):
    async def classify(
        self, transaction: ClassificationInput, allowed_accounts: Sequence[AllowedAccount]
    ) -> ClassificationProposal | None: ...


class DisabledClassificationProvider:
    """Explicit no-provider implementation; it never performs I/O."""

    async def classify(
        self, transaction: ClassificationInput, allowed_accounts: Sequence[AllowedAccount]
    ) -> ClassificationProposal | None:
        return None
