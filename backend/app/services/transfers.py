"""Conservative, deterministic matching of canonical inter-account transfers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Sequence

from app.domain.transactions import NormalizedTransaction


_REFERENCE_SUFFIX = re.compile(r"\bREF(?:ERENCE)?\s*[:#-]?\s*([A-Z0-9-]+)\s*$")


@dataclass(frozen=True, slots=True)
class TransferPair:
    id: str
    transaction_ids: tuple[str, str]
    outflow_transaction_id: str
    inflow_transaction_id: str
    amount_minor: int
    date_distance_days: int
    match_method: str
    status: str = "matched"


@dataclass(frozen=True, slots=True)
class TransferMatchResult:
    pairs: tuple[TransferPair, ...]
    needs_review: tuple[tuple[str, ...], ...]


def match_transfers(canonical: Sequence[NormalizedTransaction]) -> TransferMatchResult:
    """Match only mutual one-to-one, opposite-signed transfer candidates."""
    transactions = tuple(sorted(canonical, key=lambda transaction: transaction.id))
    candidates = _candidate_map(transactions)
    preferred = {
        transaction_id: _prefer_reference_matches(transaction_id, candidate_ids, transactions)
        for transaction_id, candidate_ids in candidates.items()
    }

    pairs: list[TransferPair] = []
    paired_ids: set[str] = set()
    for transaction in transactions:
        if transaction.id in paired_ids:
            continue
        candidate_ids = preferred.get(transaction.id, ())
        if len(candidate_ids) != 1:
            continue
        candidate_id = candidate_ids[0]
        if preferred.get(candidate_id, ()) != (transaction.id,):
            continue
        counterpart = _by_id(transactions)[candidate_id]
        outflow, inflow = (transaction, counterpart) if transaction.amount_minor < 0 else (counterpart, transaction)
        pairs.append(_pair(outflow, inflow))
        paired_ids.update((transaction.id, candidate_id))

    review_groups = _review_groups(candidates, paired_ids)
    return TransferMatchResult(
        pairs=tuple(sorted(pairs, key=lambda pair: pair.transaction_ids)),
        needs_review=review_groups,
    )


def _candidate_map(transactions: Sequence[NormalizedTransaction]) -> dict[str, tuple[str, ...]]:
    candidates: dict[str, list[str]] = {}
    for index, left in enumerate(transactions):
        for right in transactions[index + 1 :]:
            if _is_candidate(left, right):
                candidates.setdefault(left.id, []).append(right.id)
                candidates.setdefault(right.id, []).append(left.id)
    return {transaction_id: tuple(sorted(ids)) for transaction_id, ids in candidates.items()}


def _is_candidate(left: NormalizedTransaction, right: NormalizedTransaction) -> bool:
    return (
        {left.bank_account_number, right.bank_account_number} == {"1000", "1010"}
        and left.amount_minor == -right.amount_minor
        and abs((left.transaction_date - right.transaction_date).days) <= 2
        and "TRANSFER" in left.description_normalized
        and "TRANSFER" in right.description_normalized
    )


def _prefer_reference_matches(
    transaction_id: str,
    candidate_ids: tuple[str, ...],
    transactions: Sequence[NormalizedTransaction],
) -> tuple[str, ...]:
    by_id = _by_id(transactions)
    reference = _reference_suffix(by_id[transaction_id].description_normalized)
    matches = tuple(
        candidate_id
        for candidate_id in candidate_ids
        if reference is not None and reference == _reference_suffix(by_id[candidate_id].description_normalized)
    )
    return matches or candidate_ids


def _reference_suffix(description: str) -> str | None:
    match = _REFERENCE_SUFFIX.search(description)
    return match.group(1) if match else None


def _pair(outflow: NormalizedTransaction, inflow: NormalizedTransaction) -> TransferPair:
    transaction_ids = (outflow.id, inflow.id)
    payload = {
        "amount_minor": abs(outflow.amount_minor),
        "inflow_transaction_id": inflow.id,
        "outflow_transaction_id": outflow.id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return TransferPair(
        id=sha256(encoded.encode("utf-8")).hexdigest(),
        transaction_ids=transaction_ids,
        outflow_transaction_id=outflow.id,
        inflow_transaction_id=inflow.id,
        amount_minor=abs(outflow.amount_minor),
        date_distance_days=abs((outflow.transaction_date - inflow.transaction_date).days),
        match_method="reference_and_amount" if _same_reference(outflow, inflow) else "amount_and_date",
    )


def _same_reference(left: NormalizedTransaction, right: NormalizedTransaction) -> bool:
    left_reference = _reference_suffix(left.description_normalized)
    return left_reference is not None and left_reference == _reference_suffix(right.description_normalized)


def _review_groups(
    candidates: dict[str, tuple[str, ...]], paired_ids: set[str]
) -> tuple[tuple[str, ...], ...]:
    unpaired = {transaction_id for transaction_id in candidates if transaction_id not in paired_ids}
    groups: list[tuple[str, ...]] = []
    while unpaired:
        pending = [min(unpaired)]
        group: set[str] = set()
        while pending:
            transaction_id = pending.pop()
            if transaction_id in group:
                continue
            group.add(transaction_id)
            pending.extend(candidate_id for candidate_id in candidates[transaction_id] if candidate_id in unpaired)
        unpaired.difference_update(group)
        groups.append(tuple(sorted(group)))
    return tuple(sorted(groups))


def _by_id(transactions: Sequence[NormalizedTransaction]) -> dict[str, NormalizedTransaction]:
    return {transaction.id: transaction for transaction in transactions}
