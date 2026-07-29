"""Cash-basis profit-and-loss aggregation behavior."""

from datetime import date, datetime, timezone

from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.transactions import Direction, NormalizedTransaction
from app.services.pnl import build_pnl


def _transaction(transaction_id: str, amount_minor: int, day: int = 1) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction_id,
        raw_record_id=f"raw-{transaction_id}",
        bank_transaction_id=f"bank-{transaction_id}",
        transaction_date=date(2026, 4, day),
        posted_date=date(2026, 4, day),
        description_original=transaction_id,
        description_normalized=transaction_id,
        amount_minor=amount_minor,
        currency="USD",
        direction=Direction.INFLOW if amount_minor > 0 else Direction.OUTFLOW,
        bank_account_number="1000",
    )


def _decision(
    transaction_id: str, account_number: str, transaction_type: TransactionType
) -> ClassificationDecision:
    return ClassificationDecision(
        id=f"decision-{transaction_id}",
        transaction_id=transaction_id,
        account_number=account_number,
        transaction_type=transaction_type,
        source=DecisionSource.HARD_RULE,
        confidence_basis_points=10000,
        approval_status=ApprovalStatus.APPROVED,
        needs_review=False,
        explanation="approved test decision",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def test_pnl_converts_bank_signs_and_calculates_gross_and_net_profit() -> None:
    """Using bank signs directly would make costs inflate profit."""
    transactions = (
        _transaction("revenue", 1_000),
        _transaction("refund", -100),
        _transaction("materials", -300),
        _transaction("payroll", -200),
    )
    decisions = (
        _decision("revenue", "4000", TransactionType.REVENUE),
        _decision("refund", "4100", TransactionType.REFUND),
        _decision("materials", "5000", TransactionType.COGS),
        _decision("payroll", "6000", TransactionType.OPERATING_EXPENSE),
    )

    report = build_pnl(transactions, decisions, date(2026, 4, 1), date(2026, 4, 30))

    assert report.total_revenue_minor == 900
    assert report.total_cogs_minor == 300
    assert report.gross_profit_minor == 600
    assert report.total_operating_expenses_minor == 200
    assert report.net_profit_minor == 400
    assert report.revenue_lines[0].total == 1_000
    assert report.revenue_lines[0].count == 1
    assert report.revenue_lines[-1].transaction_ids == ("refund",)
