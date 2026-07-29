from datetime import date

import pytest

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
        "counterparty": "Example Vendor",
        "account_number": "6030",
        "confidence": 0.87,
        "needs_review": False,
        "evidence": ("Description contains vendor name",),
    }
    values.update(changes)
    return ClassificationProposal(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_proposal",
    [
        proposal(account_number="9999"),
        proposal(transaction_type="revenue", account_number="6030"),
        proposal(amount_minor=-1000),
        proposal(transaction_date=date(2026, 4, 1)),
        proposal(bank_transaction_id="changed-bank-id"),
        proposal(transaction_id="changed-transaction-id"),
    ],
)
def test_post_validation_rejects_untrusted_or_inconsistent_ai_fields(
    bad_proposal: ClassificationProposal,
) -> None:
    """Accepting provider-owned IDs, amounts, dates, or bad accounts would corrupt bank lineage."""
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
