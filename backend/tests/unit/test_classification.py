from datetime import date

import pytest

from app.services import classification as classification_service
from app.domain.classification import ApprovalStatus, DecisionSource, TransactionType
from app.domain.transactions import Direction, NormalizedTransaction
from app.services.classification import (
    ClassificationContext,
    classify_transaction,
)


def tx(
    description: str,
    amount_minor: int,
    *,
    transaction_id: str = "tx-1",
    bank_account_number: str = "1000",
) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction_id,
        raw_record_id=f"raw-{transaction_id}",
        bank_transaction_id=f"bank-{transaction_id}",
        transaction_date=date(2026, 4, 1),
        posted_date=date(2026, 4, 1),
        description_original=description,
        description_normalized=description.upper(),
        amount_minor=amount_minor,
        currency="USD",
        direction=Direction.INFLOW if amount_minor > 0 else Direction.OUTFLOW,
        bank_account_number=bank_account_number,
    )


@pytest.mark.parametrize("bank_account_number", ["1000", "1010"])
def test_matched_transfer_takes_priority_and_requires_review(bank_account_number: str) -> None:
    """Removing transfer precedence would misstate an internal movement as business activity."""
    result = classify_transaction(
        tx("TRANSFER FROM SAVINGS", 125000, bank_account_number=bank_account_number),
        ClassificationContext(matched_transfer_ids=frozenset({"tx-1"})),
    )

    assert result.account_number == bank_account_number
    assert result.transaction_type is TransactionType.TRANSFER
    assert result.source is DecisionSource.HARD_RULE
    assert result.approval_status is ApprovalStatus.SUGGESTED
    assert result.needs_review is True
    assert result.confidence_basis_points == 10000


@pytest.mark.parametrize(
    ("description", "amount_minor", "account_number", "transaction_type"),
    [
        ("OWNER CAPITAL CONTRIBUTION", 200000, "3000", TransactionType.OWNER_ACTIVITY),
        ("OWNER DRAW", -200000, "3000", TransactionType.OWNER_ACTIVITY),
        ("REFUND TO ACME CUSTOMER", -4500, "4100", TransactionType.REFUND),
        ("COMMERCIAL TOOL PACKAGE", -129900, "1500", TransactionType.FIXED_ASSET),
    ],
)
def test_high_risk_hard_rules_require_review(
    description: str, amount_minor: int, account_number: str, transaction_type: TransactionType
) -> None:
    """Auto-approving owner, refund, or asset activity would bypass required human review."""
    result = classify_transaction(tx(description, amount_minor), ClassificationContext())

    assert (result.account_number, result.transaction_type) == (account_number, transaction_type)
    assert result.approval_status is ApprovalStatus.SUGGESTED
    assert result.needs_review is True


@pytest.mark.parametrize(
    ("description", "account_number"),
    [
        ("ACME MAINTENANCE SERVICE PLAN", "4020"),
        ("ACME NEW INSTALL", "4010"),
        ("ACME REPAIR INVOICE", "4000"),
    ],
)
def test_low_risk_customer_inflows_are_auto_approved_revenue(
    description: str, account_number: str
) -> None:
    """A wrong revenue bucket would distort cash-basis revenue reporting."""
    result = classify_transaction(tx(description, 29900), ClassificationContext())

    assert result.account_number == account_number
    assert result.transaction_type is TransactionType.REVENUE
    assert result.approval_status is ApprovalStatus.APPROVED
    assert result.needs_review is False
    assert result.confidence_basis_points == 10000


@pytest.mark.parametrize(
    ("description", "account_number"),
    [
        ("HOMEDEPOT #45", "5000"),
        ("LOWE'S", "5000"),
        ("LOWES.COM REF 402", "5000"),
        ("FERGUSON", "5000"),
        ("SUPPLYHOUSE", "5000"),
        ("GRAINGER", "5000"),
        ("ABC PLUMBING SUPPLY", "5000"),
        ("CES ELECTRICAL", "5000"),
        ("RIVERA SUBCONTRACTOR", "5010"),
        ("APEX SERVICES", "5010"),
        ("NORTHLINE LABOR", "5010"),
        ("PRECISION INSTALL", "5010"),
        ("METRO HANDYMAN", "5010"),
        ("ADP PAYROLL", "6000"),
        ("OFFICE RENT", "6010"),
        ("SHELL FUEL", "6020"),
        ("SHELL OIL", "6020"),
        ("BP#98231", "6020"),
        ("EXXONMOBIL", "6020"),
        ("SPEEDWAY", "6020"),
        ("QUICKBOOKS ONLINE", "6030"),
        ("GOOGLE ADS", "6040"),
        ("HISCOX INSURANCE", "6050"),
        ("CON EDISON", "6060"),
        ("CPA PROFESSIONAL SERVICES", "6070"),
        ("MONTHLY SERVICE FEE", "6080"),
        ("STAPLES OFFICE SUPPLIES", "6090"),
        ("FLEET AUTO CARE", "6100"),
    ],
)
def test_known_outflow_merchants_map_to_whitelisted_accounts(description: str, account_number: str) -> None:
    """A merchant-rule regression would send operating costs outside their challenge account."""
    result = classify_transaction(tx(description, -1099), ClassificationContext())

    assert result.account_number == account_number
    assert result.approval_status is ApprovalStatus.APPROVED
    assert result.needs_review is False


def test_possible_duplicate_cannot_be_auto_approved() -> None:
    """Ignoring the duplicate risk gate would allow a lookalike inflow into P&L twice."""
    result = classify_transaction(
        tx("ACME REPAIR INVOICE", 29900),
        ClassificationContext(possible_duplicate_ids=frozenset({"tx-1"})),
    )

    assert result.transaction_type is TransactionType.REVENUE
    assert result.approval_status is ApprovalStatus.SUGGESTED
    assert result.needs_review is True


def test_unmatched_transfer_candidate_cannot_fall_back_to_revenue() -> None:
    """A one-sided transfer inflow must not inflate revenue while awaiting its pair."""
    result = classify_transaction(
        tx("TRANSFER REF ABC", 50000),
        ClassificationContext(unmatched_transfer_ids=frozenset({"tx-1"})),
    )

    assert result.transaction_type is TransactionType.TRANSFER
    assert result.account_number == "1000"
    assert result.approval_status is ApprovalStatus.SUGGESTED
    assert result.needs_review is True


@pytest.mark.parametrize(
    ("description", "amount_minor", "forbidden_type"),
    [
        ("OWNER CAPITAL CONTRIBUTION", -200000, TransactionType.OWNER_ACTIVITY),
        ("OWNER DRAW", 200000, TransactionType.OWNER_ACTIVITY),
        ("REFUND TO ACME CUSTOMER", 4500, TransactionType.REFUND),
        ("COMMERCIAL TOOL PACKAGE", 129900, TransactionType.FIXED_ASSET),
        ("ADP PAYROLL", 1099, TransactionType.OPERATING_EXPENSE),
    ],
)
def test_directional_rules_do_not_match_the_opposite_cash_direction(
    description: str, amount_minor: int, forbidden_type: TransactionType
) -> None:
    """Removing a rule's direction guard would approve an accounting-sign contradiction."""
    result = classify_transaction(tx(description, amount_minor))

    assert result.transaction_type is not forbidden_type


def test_accounting_invariant_rejects_account_type_mismatch() -> None:
    """A revenue decision posted to an expense account would corrupt P&L and QBO mapping."""
    with pytest.raises(ValueError, match="account type"):
        classification_service.validate_accounting_decision(
            tx("ACME REPAIR INVOICE", 10000),
            "6000",
            TransactionType.REVENUE,
        )


def test_accounting_invariant_rejects_cash_direction_mismatch() -> None:
    """An inflow classified as an operating expense must never become approved."""
    with pytest.raises(ValueError, match="cash direction"):
        classification_service.validate_accounting_decision(
            tx("ADP PAYROLL REVERSAL", 10000),
            "6000",
            TransactionType.OPERATING_EXPENSE,
        )
