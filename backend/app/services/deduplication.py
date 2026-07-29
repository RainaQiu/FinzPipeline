"""Deterministic duplicate decisions for normalized bank transactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Sequence

from app.domain.transactions import NormalizedTransaction


class DuplicateStatus(StrEnum):
    UNIQUE = "unique"
    CANONICAL = "canonical"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    POSSIBLE_DUPLICATE = "possible_duplicate"


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    canonical_transactions: tuple[NormalizedTransaction, ...]
    duplicate_to_canonical: Mapping[str, str]
    conflicts: tuple[NormalizedTransaction, ...]
    possible_duplicates: tuple[NormalizedTransaction, ...]
    status_by_id: Mapping[str, DuplicateStatus]

    def __post_init__(self) -> None:
        object.__setattr__(self, "duplicate_to_canonical", MappingProxyType(dict(self.duplicate_to_canonical)))
        object.__setattr__(self, "status_by_id", MappingProxyType(dict(self.status_by_id)))

    @property
    def canonical_ids(self) -> tuple[str, ...]:
        return tuple(transaction.id for transaction in self.canonical_transactions)


def deduplicate(transactions: Sequence[NormalizedTransaction]) -> DeduplicationResult:
    """Keep exact same-ID canonicals and route reused-ID disagreements to review."""
    by_bank_id: dict[str, list[NormalizedTransaction]] = {}
    for transaction in transactions:
        by_bank_id.setdefault(transaction.bank_transaction_id, []).append(transaction)

    canonical: list[NormalizedTransaction] = []
    duplicates: dict[str, str] = {}
    statuses: dict[str, DuplicateStatus] = {}
    conflicts: list[NormalizedTransaction] = []

    for group in by_bank_id.values():
        first = group[0]
        if len(group) == 1:
            canonical.append(first)
            statuses[first.id] = DuplicateStatus.UNIQUE
        elif all(_business_fields(transaction) == _business_fields(first) for transaction in group[1:]):
            canonical.append(first)
            statuses[first.id] = DuplicateStatus.CANONICAL
            for duplicate in group[1:]:
                duplicates[duplicate.id] = first.id
                statuses[duplicate.id] = DuplicateStatus.DUPLICATE
        else:
            conflicts.extend(group)
            for conflict in group:
                statuses[conflict.id] = DuplicateStatus.CONFLICT

    possible_duplicates = _possible_duplicates(canonical)
    for transaction in possible_duplicates:
        statuses[transaction.id] = DuplicateStatus.POSSIBLE_DUPLICATE

    return DeduplicationResult(
        canonical_transactions=tuple(canonical),
        duplicate_to_canonical=duplicates,
        conflicts=tuple(conflicts),
        possible_duplicates=possible_duplicates,
        status_by_id=statuses,
    )


def _business_fields(transaction: NormalizedTransaction) -> tuple[object, ...]:
    return (
        transaction.bank_account_number,
        transaction.transaction_date,
        transaction.posted_date,
        transaction.amount_minor,
        transaction.currency,
        transaction.description_normalized,
    )


def _possible_duplicates(
    canonical: Sequence[NormalizedTransaction],
) -> tuple[NormalizedTransaction, ...]:
    """Annotate only conservative, same-account near-date lookalikes; never remove them."""
    possible_ids: set[str] = set()
    for index, left in enumerate(canonical):
        for right in canonical[index + 1 :]:
            if (
                left.bank_account_number == right.bank_account_number
                and left.amount_minor == right.amount_minor
                and abs((left.transaction_date - right.transaction_date).days) <= 2
                and _descriptions_are_similar(left.description_normalized, right.description_normalized)
            ):
                possible_ids.update((left.id, right.id))
    return tuple(transaction for transaction in canonical if transaction.id in possible_ids)


def _descriptions_are_similar(left: str, right: str) -> bool:
    if left == right:
        return True
    left_tokens = frozenset(left.split())
    right_tokens = frozenset(right.split())
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= 0.8
