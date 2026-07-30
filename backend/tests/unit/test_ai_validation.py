from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.classification import ApprovalStatus, DecisionSource
from app.domain.transactions import Direction, NormalizedTransaction
from app.integrations.ai.protocol import ClassificationProposal
from app.services.classification import (
    ClassificationContext,
    ProposalValidationError,
    classify_transaction,
    validate_proposal,
)


def tx(description: str, amount_minor: int = -1000) -> NormalizedTransaction:
    return NormalizedTransaction(
        id="tx-ai",
        raw_record_id="raw-ai",
        bank_transaction_id="bank-ai",
        transaction_date=date(2026, 4, 1),
        posted_date=date(2026, 4, 1),
        description_original=description,
        description_normalized=description.upper(),
        amount_minor=amount_minor,
        currency="USD",
        direction=Direction.INFLOW if amount_minor > 0 else Direction.OUTFLOW,
        bank_account_number="1000",
    )


def proposal(**changes: object) -> ClassificationProposal:
    values: dict[str, object] = {
        "transaction_type": "operating_expense",
        "account_number": "6030",
        "explanation": "The normalized description resembles a software subscription.",
        "confidence_basis_points": 8700,
    }
    values.update(changes)
    return ClassificationProposal(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount_minor", -1000),
        ("transaction_date", "2026-04-01"),
        ("bank_transaction_id", "changed-bank-id"),
        ("transaction_id", "changed-transaction-id"),
        ("counterparty", "Example Vendor"),
        ("needs_review", False),
        ("evidence", ["provider-owned evidence"]),
    ],
)
def test_proposal_schema_rejects_every_field_outside_candidate_authority(
    field: str, value: object
) -> None:
    """Adding provider-owned transaction or approval fields would expand AI authority."""
    with pytest.raises(ValidationError):
        proposal(**{field: value})


@pytest.mark.parametrize("bad_confidence", [-1, 10001, 87.5, True, "8700"])
def test_proposal_schema_requires_integer_basis_points_in_range(
    bad_confidence: object,
) -> None:
    """A float, coercion, or out-of-range score would weaken the review threshold contract."""
    with pytest.raises(ValidationError):
        proposal(confidence_basis_points=bad_confidence)


@pytest.mark.parametrize(
    "bad_proposal",
    [
        proposal(account_number="9999"),
        proposal(transaction_type="revenue", account_number="6030"),
        proposal(transaction_type="revenue", account_number="4000"),
    ],
)
def test_post_validation_rejects_unknown_or_directionally_inconsistent_ai_output(
    bad_proposal: ClassificationProposal,
) -> None:
    """Unknown accounts or a type/direction mismatch could corrupt the ledger."""
    with pytest.raises(ProposalValidationError):
        validate_proposal(bad_proposal, tx("UNRECOGNIZED SOFTWARE VENDOR"), None)


def test_post_validation_rejects_ai_attempt_to_override_hard_rule() -> None:
    """An AI proposal must not displace deterministic accounting treatment."""
    transaction = tx("QUICKBOOKS ONLINE")
    hard_rule = classify_transaction(transaction, ClassificationContext())

    with pytest.raises(ProposalValidationError):
        validate_proposal(proposal(account_number="6040"), transaction, hard_rule)


def test_ai_only_classification_is_suggested_and_requires_review() -> None:
    """Provider confidence alone must never approve an otherwise unknown transaction."""
    result = classify_transaction(
        tx("UNRECOGNIZED SOFTWARE VENDOR"),
        ClassificationContext(ai_proposal=proposal()),
    )

    assert result.source is DecisionSource.AI
    assert result.approval_status is ApprovalStatus.SUGGESTED
    assert result.needs_review is True
    assert result.confidence_basis_points == 8700
    assert result.explanation == (
        "AI candidate: The normalized description resembles a software subscription. "
        "Human review is required."
    )
