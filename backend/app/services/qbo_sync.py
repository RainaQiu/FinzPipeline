"""Plan and explicitly execute safe, idempotent QuickBooks exports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from app.domain.accounts import parse_account
from app.domain.accounting import OutboxItem, OutboxStatus
from app.integrations.quickbooks.protocol import (
    QboCreateResult,
    QboGatewayError,
    QboWriteNotAuthorizedError,
    QuickBooksGateway,
)


@dataclass(frozen=True, slots=True)
class SyncCandidate:
    transaction: object
    approved: object
    transfer_pair: object | None = None


def make_idempotency_key(realm: str, transaction: str, version: int) -> str:
    return f"qbo:{realm}:{transaction}:{version}"


def _value(source: object, *names: str) -> object:
    for name in names:
        if isinstance(source, Mapping) and name in source:
            return source[name]
        value = getattr(source, name, None)
        if value is not None:
            return value
    raise ValueError(f"missing required value: {names[0]}")


def _optional_value(source: object, *names: str) -> object | None:
    try:
        return _value(source, *names)
    except ValueError:
        return None


def _amount(transaction: object) -> Decimal:
    minor = _optional_value(transaction, "amount_minor")
    if minor is not None:
        return Decimal(int(minor)) / Decimal(100)
    return Decimal(str(_value(transaction, "amount")))


def _dollars(transaction: object, *, absolute: bool = True) -> str:
    amount = _amount(transaction)
    if absolute:
        amount = abs(amount)
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _account(transaction: object) -> str:
    return str(_value(transaction, "bank_account_number", "bank_account"))


def _transaction_id(transaction: object) -> str:
    return str(_value(transaction, "id", "transaction_id"))


def _version(candidate: SyncCandidate) -> int:
    return int(_optional_value(candidate.approved, "version") or _optional_value(candidate.transaction, "version") or 1)


def _type(candidate: SyncCandidate) -> str:
    kind = _optional_value(candidate.approved, "transaction_type", "kind")
    if kind is None:
        kind = _value(candidate.transaction, "kind", "transaction_type")
    return str(getattr(kind, "value", kind))


def _decision_account(candidate: SyncCandidate) -> str:
    account = str(_value(candidate.approved, "account_number", "account"))
    parse_account(account)
    return account


def _is_approved(candidate: SyncCandidate) -> bool:
    approval_status = _optional_value(candidate.approved, "approval_status")
    return str(getattr(approval_status, "value", approval_status)) == "approved"


def _deposit(bank_account: str, decision_account: str, amount: str) -> Mapping[str, object]:
    return {
        "DepositToAccountRef": {"value": bank_account},
        "Line": (
            {
                "Amount": amount,
                "DetailType": "DepositLineDetail",
                "DepositLineDetail": {"AccountRef": {"value": decision_account}},
            },
        ),
    }


def _purchase(bank_account: str, decision_account: str, amount: str) -> Mapping[str, object]:
    return {
        "PaymentType": "Cash",
        "AccountRef": {"value": bank_account},
        "Line": (
            {
                "Amount": amount,
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": decision_account}},
            },
        ),
    }


def _transfer_pair_id(pair: object, transaction: object) -> str:
    if isinstance(pair, str):
        return pair
    value = _optional_value(pair, "pair_id", "transfer_pair_id", "id")
    if value is not None:
        return str(value)
    return _transaction_id(transaction)


def _transfer_payload(transaction: object, pair: object) -> Mapping[str, object]:
    other = _optional_value(pair, "transaction", "counterpart", "paired_transaction") or pair
    from_account, to_account = _account(transaction), _account(other)
    amount = _amount(transaction)
    if from_account != "1000" or amount >= 0:
        raise ValueError("transfer transaction must be the 1000 outflow leg")
    if to_account != "1010":
        raise ValueError("transfer destination must be bank account 1010")
    pair_amount = _optional_value(other, "amount_minor", "amount")
    if pair_amount is not None:
        paired_value = _amount(other)
        if paired_value <= 0 or abs(paired_value) != abs(amount):
            raise ValueError("transfer pair amounts must be equal and opposite")
    return {
        "FromAccountRef": {"value": from_account},
        "ToAccountRef": {"value": to_account},
        "Amount": _dollars(transaction),
    }


def _outbox_repository(repo: object) -> object:
    return getattr(repo, "outbox", repo)


async def _add_item(repo: object, item: OutboxItem) -> OutboxItem:
    target = _outbox_repository(repo)
    method = getattr(target, "add", None) or getattr(target, "save_outbox_item", None)
    if method is None:
        raise TypeError("repository must provide add(item)")
    return await method(item)


async def plan_sync(candidates: list[SyncCandidate] | tuple[SyncCandidate, ...], realm: str, repo: object) -> tuple[OutboxItem, ...]:
    """Persist immutable export intents; this function never calls QuickBooks."""
    planned: list[OutboxItem] = []
    seen_transfer_keys: set[str] = set()
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        if not _is_approved(candidate):
            raise ValueError("classification decision must be approved before QBO sync")
        transaction_type = _type(candidate)
        transaction = candidate.transaction
        if transaction_type == "transfer":
            if candidate.transfer_pair is None:
                raise ValueError("transfer candidate requires transfer_pair")
            pair_id = _transfer_pair_id(candidate.transfer_pair, transaction)
            key = f"qbo:{realm}:transfer:{pair_id}"
            if key in seen_transfer_keys:
                continue
            seen_transfer_keys.add(key)
            kind, payload, transaction_id = "Transfer", _transfer_payload(transaction, candidate.transfer_pair), pair_id
        else:
            transaction_id = _transaction_id(transaction)
            key = make_idempotency_key(realm, transaction_id, _version(candidate))
            account, amount, bank = _decision_account(candidate), _dollars(transaction), _account(transaction)
            direction = str(getattr(_optional_value(transaction, "direction"), "value", _optional_value(transaction, "direction") or ""))
            if transaction_type in {"revenue", "owner_contribution"} or (
                transaction_type == "owner_activity" and direction == "inflow"
            ):
                kind, payload = "Deposit", _deposit(bank, account, amount)
            elif transaction_type == "refund":
                kind, payload = "Deposit", _deposit(bank, account, _dollars(transaction, absolute=False))
            elif transaction_type in {
                "cogs",
                "expense",
                "operating_expense",
                "asset",
                "fixed_asset",
                "owner_activity",
                "owner_distribution",
            }:
                kind, payload = "Purchase", _purchase(bank, account, amount)
            else:
                raise ValueError(f"unsupported QBO transaction type: {transaction_type}")
        item = OutboxItem(
            id=key,
            realm_id=realm,
            transaction_id=transaction_id,
            classification_version=_version(candidate),
            payload_kind=kind,
            payload=payload,
            status=OutboxStatus.PENDING,
            created_at=now,
            idempotency_key=key,
            classification_decision_id=str(_optional_value(candidate.approved, "id") or "") or None,
        )
        planned.append(await _add_item(repo, item))
    return tuple(planned)


async def _transition(repo: object, item_id: str, status: OutboxStatus, **kwargs: object) -> OutboxItem:
    target = _outbox_repository(repo)
    return await target.transition(item_id, status, **kwargs)


def _retry_delay_seconds(attempt_count: int) -> int:
    return min(3600, 2**attempt_count * 60)


def _retry_transition_values(attempt_count: int) -> Mapping[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "updated_at": now,
        "next_attempt_at": now + timedelta(seconds=_retry_delay_seconds(attempt_count)),
    }


async def process_outbox_item(
    item_id: str, gateway: QuickBooksGateway, repo: object, *, allow_writes: bool = False
) -> OutboxItem:
    """Execute one intent only when an explicit write permission is supplied."""
    if not allow_writes:
        raise QboWriteNotAuthorizedError("QuickBooks writes require allow_writes=True")
    target = _outbox_repository(repo)
    item = await target.get(item_id)
    if item is None:
        raise KeyError(item_id)
    if item.status is OutboxStatus.SUCCEEDED:
        return item
    if item.status in {OutboxStatus.PENDING, OutboxStatus.RETRYABLE_FAILED}:
        item = await _transition(repo, item_id, OutboxStatus.PROCESSING)
    if item.status is not OutboxStatus.PROCESSING:
        raise ValueError(f"outbox item {item_id} is not executable")
    try:
        result: QboCreateResult = await gateway.create_entity(item.payload_kind, item.payload)
    except QboGatewayError as error:
        status = OutboxStatus.RETRYABLE_FAILED if error.retryable else OutboxStatus.PERMANENT_FAILED
        retry_values = _retry_transition_values(item.attempt_count) if error.retryable else {}
        return await _transition(repo, item_id, status, **retry_values, last_error_code=error.code)
    except TimeoutError:
        retry_values = _retry_transition_values(item.attempt_count)
        return await _transition(
            repo,
            item_id,
            OutboxStatus.RETRYABLE_FAILED,
            **retry_values,
            last_error_code="timeout",
        )
    except (KeyError, ValueError, TypeError):
        return await _transition(repo, item_id, OutboxStatus.PERMANENT_FAILED, last_error_code="invariant")
    return await _transition(
        repo,
        item_id,
        OutboxStatus.SUCCEEDED,
        qbo_entity_id=result.entity_id,
        sync_token=result.sync_token,
    )
