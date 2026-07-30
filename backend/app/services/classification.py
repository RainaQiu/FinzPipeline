"""Deterministic classification and defensive validation of AI suggestions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timezone
from hashlib import sha256

from app.domain.accounts import ACCOUNT_DEFINITIONS, AccountType, parse_account
from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.rules import RULES, RuleDefinition
from app.domain.transactions import Direction, NormalizedTransaction
from app.integrations.ai.protocol import ClassificationProposal


class ProposalValidationError(ValueError):
    """Raised when an AI proposal exceeds its narrow, advisory authority."""


class AccountingInvariantError(ValueError):
    """Raised when an account, type, and cash direction cannot coexist safely."""


@dataclass(frozen=True, slots=True)
class ClassificationContext:
    matched_transfer_ids: frozenset[str] = frozenset()
    unmatched_transfer_ids: frozenset[str] = frozenset()
    possible_duplicate_ids: frozenset[str] = frozenset()
    ai_proposal: ClassificationProposal | None = None


@dataclass(frozen=True, slots=True)
class ValidatedProposal:
    proposal: ClassificationProposal
    transaction_type: TransactionType
    confidence_basis_points: int


def classify_transaction(
    transaction: NormalizedTransaction, context: ClassificationContext | None = None
) -> ClassificationDecision:
    """Return the highest-precedence safe decision; AI remains advisory only."""
    context = context or ClassificationContext()
    if transaction.id in context.matched_transfer_ids:
        return _decision(
            transaction, transaction.bank_account_number, TransactionType.TRANSFER, DecisionSource.HARD_RULE,
            10000, True, "matched_transfer", "Matched transfer pair requires human review."
        )
    if transaction.id in context.unmatched_transfer_ids:
        return _decision(
            transaction, transaction.bank_account_number, TransactionType.TRANSFER, DecisionSource.HARD_RULE,
            0, True, "unmatched_transfer", "Unmatched transfer candidate requires human review."
        )

    rule = _matching_rule(transaction)
    if rule is not None:
        decision = _rule_decision(transaction, rule)
    elif transaction.direction is Direction.INFLOW:
        decision = _decision(
            transaction, "4000", TransactionType.REVENUE, DecisionSource.HARD_RULE,
            10000, False, "customer_inflow_fallback",
            "Fallback: explicit customer inflow without a more specific revenue rule."
        )
    elif context.ai_proposal is not None:
        validated = validate_proposal(context.ai_proposal, transaction, None)
        decision = _decision(
            transaction, validated.proposal.account_number, validated.transaction_type,
            DecisionSource.AI, validated.confidence_basis_points, True, "ai_proposal",
            f"AI candidate: {validated.proposal.explanation.strip()} Human review is required."
        )
    else:
        decision = _decision(
            transaction, "6000", TransactionType.OPERATING_EXPENSE, DecisionSource.HUMAN,
            0, True, "unknown_outflow", "Unknown outflow requires human review."
        )
    if transaction.id in context.possible_duplicate_ids:
        return replace(
            decision,
            approval_status=ApprovalStatus.SUGGESTED,
            needs_review=True,
            explanation=f"{decision.explanation} Possible duplicate requires human review.",
        )
    return decision


def validate_proposal(
    proposal: ClassificationProposal,
    transaction: NormalizedTransaction,
    rule_result: ClassificationDecision | None,
) -> ValidatedProposal:
    """Validate a typed proposal after deterministic rules have had precedence."""
    if (
        not isinstance(proposal.confidence_basis_points, int)
        or isinstance(proposal.confidence_basis_points, bool)
        or not 0 <= proposal.confidence_basis_points <= 10000
    ):
        raise ProposalValidationError(
            "proposal confidence_basis_points must be an integer between 0 and 10000"
        )
    if not isinstance(proposal.explanation, str) or not proposal.explanation.strip():
        raise ProposalValidationError("proposal explanation must be non-empty")
    try:
        transaction_type = TransactionType(proposal.transaction_type)
        validate_accounting_decision(
            transaction,
            proposal.account_number,
            transaction_type,
        )
    except (ValueError, TypeError) as exc:
        raise ProposalValidationError("proposal has unsupported account or transaction type") from exc
    if rule_result is not None:
        raise ProposalValidationError("AI may not override a deterministic classification")
    return ValidatedProposal(
        proposal=proposal,
        transaction_type=transaction_type,
        confidence_basis_points=proposal.confidence_basis_points,
    )


def _matching_rule(transaction: NormalizedTransaction) -> RuleDefinition | None:
    return next((rule for rule in RULES if rule.matches(transaction.description_normalized, transaction.direction)), None)


def _rule_decision(transaction: NormalizedTransaction, rule: RuleDefinition) -> ClassificationDecision:
    return _decision(
        transaction, rule.account_number, rule.transaction_type, DecisionSource.HARD_RULE,
        _clamp_basis_points(7000 + 3000), rule.requires_review, rule.rule_id,
        f"Hard rule {rule.rule_id} matched transaction description."
    )


def _decision(
    transaction: NormalizedTransaction,
    account_number: str,
    transaction_type: TransactionType,
    source: DecisionSource,
    confidence_basis_points: int,
    needs_review: bool,
    rule_id: str,
    explanation: str,
) -> ClassificationDecision:
    validate_accounting_decision(transaction, account_number, transaction_type)
    approval_status = ApprovalStatus.SUGGESTED if needs_review else ApprovalStatus.APPROVED
    decision_id = sha256(
        f"{transaction.id}|{account_number}|{transaction_type.value}|{source.value}|{rule_id}".encode()
    ).hexdigest()
    return ClassificationDecision(
        id=decision_id,
        transaction_id=transaction.id,
        account_number=account_number,
        transaction_type=transaction_type,
        source=source,
        confidence_basis_points=_clamp_basis_points(confidence_basis_points),
        approval_status=approval_status,
        needs_review=needs_review,
        explanation=explanation,
        created_at=datetime.combine(transaction.posted_date, time.min, tzinfo=timezone.utc),
    )


def validate_accounting_decision(
    transaction: NormalizedTransaction,
    account_number: str,
    transaction_type: TransactionType,
) -> None:
    """Enforce the same account/type/direction invariant at every approval boundary."""
    account = parse_account(account_number)
    if not _account_type_matches(account.account_type, transaction_type):
        raise AccountingInvariantError(
            "account type conflicts with transaction type"
        )
    if not _direction_matches(transaction.direction, transaction_type):
        raise AccountingInvariantError(
            "transaction type conflicts with cash direction"
        )


def _account_type_matches(account_type: AccountType, transaction_type: TransactionType) -> bool:
    return {
        TransactionType.REVENUE: account_type is AccountType.REVENUE,
        TransactionType.COGS: account_type is AccountType.COST_OF_GOODS_SOLD,
        TransactionType.OPERATING_EXPENSE: account_type is AccountType.OPERATING_EXPENSE,
        TransactionType.REFUND: account_type is AccountType.CONTRA_REVENUE,
        TransactionType.TRANSFER: account_type is AccountType.ASSET,
        TransactionType.OWNER_ACTIVITY: account_type is AccountType.EQUITY,
        TransactionType.FIXED_ASSET: account_type is AccountType.ASSET,
    }[transaction_type]


def _direction_matches(direction: Direction, transaction_type: TransactionType) -> bool:
    if transaction_type is TransactionType.REVENUE:
        return direction is Direction.INFLOW
    if transaction_type in {
        TransactionType.COGS,
        TransactionType.OPERATING_EXPENSE,
        TransactionType.REFUND,
        TransactionType.FIXED_ASSET,
    }:
        return direction is Direction.OUTFLOW
    return transaction_type in {
        TransactionType.TRANSFER,
        TransactionType.OWNER_ACTIVITY,
    }


def _clamp_basis_points(value: float | int) -> int:
    return max(0, min(10000, round(value)))
