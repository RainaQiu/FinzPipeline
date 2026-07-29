"""Deterministic cash-basis P&L aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable, Mapping

from app.domain.accounting import PnlLine, ProfitAndLoss
from app.domain.accounts import ACCOUNT_DEFINITIONS, PnlBehavior
from app.domain.classification import ApprovalStatus, ClassificationDecision, TransactionType
from app.domain.transactions import NormalizedTransaction


_EXCLUDED_TRANSACTION_TYPES = frozenset(
    {
        TransactionType.TRANSFER,
        TransactionType.OWNER_ACTIVITY,
        TransactionType.FIXED_ASSET,
    }
)
_PNL_BEHAVIORS = (
    PnlBehavior.REVENUE,
    PnlBehavior.REFUND,
    PnlBehavior.COST_OF_GOODS_SOLD,
    PnlBehavior.OPERATING_EXPENSE,
)


def _latest_approved_decisions(
    decisions: Iterable[ClassificationDecision] | Mapping[str, ClassificationDecision],
) -> Mapping[str, ClassificationDecision]:
    """Select the newest approved decision in each append-only decision history."""
    values = decisions.values() if isinstance(decisions, Mapping) else decisions
    latest: dict[str, ClassificationDecision] = {}
    for decision in values:
        if decision.approval_status is not ApprovalStatus.APPROVED:
            continue
        current = latest.get(decision.transaction_id)
        if current is None or (decision.version, decision.created_at, decision.id) > (
            current.version,
            current.created_at,
            current.id,
        ):
            latest[decision.transaction_id] = decision
    return latest


def _display_amount(amount_minor: int, behavior: PnlBehavior) -> int:
    if behavior in {PnlBehavior.REVENUE, PnlBehavior.REFUND}:
        return amount_minor
    if behavior in {PnlBehavior.COST_OF_GOODS_SOLD, PnlBehavior.OPERATING_EXPENSE}:
        return -amount_minor
    raise ValueError(f"Account behavior does not belong in P&L: {behavior}")


def _lines_for(behavior: PnlBehavior, totals: Mapping[str, int], ids: Mapping[str, list[str]]) -> tuple[PnlLine, ...]:
    return tuple(
        PnlLine(
            account_number=account.number,
            account_name=account.name,
            total_minor=totals[account.number],
            transaction_count=len(ids[account.number]),
            transaction_ids=tuple(ids[account.number]),
        )
        for account in ACCOUNT_DEFINITIONS.values()
        if account.pnl_behavior is behavior
    )


def build_pnl(
    transactions: Iterable[NormalizedTransaction],
    decisions: Iterable[ClassificationDecision] | Mapping[str, ClassificationDecision],
    start_date: date,
    end_date: date,
) -> ProfitAndLoss:
    """Build an immutable cash-basis P&L from canonical caller-provided transactions."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")

    totals: dict[str, int] = defaultdict(int)
    transaction_ids: dict[str, list[str]] = defaultdict(list)
    approved = _latest_approved_decisions(decisions)
    for transaction in transactions:
        if not start_date <= transaction.transaction_date <= end_date:
            continue
        decision = approved.get(transaction.id)
        if decision is None or decision.transaction_type in _EXCLUDED_TRANSACTION_TYPES:
            continue
        account = ACCOUNT_DEFINITIONS[decision.account_number]
        if account.pnl_behavior not in _PNL_BEHAVIORS:
            continue
        totals[account.number] += _display_amount(transaction.amount_minor, account.pnl_behavior)
        transaction_ids[account.number].append(transaction.id)

    revenue_lines = _lines_for(PnlBehavior.REVENUE, totals, transaction_ids) + _lines_for(
        PnlBehavior.REFUND, totals, transaction_ids
    )
    cogs_lines = _lines_for(PnlBehavior.COST_OF_GOODS_SOLD, totals, transaction_ids)
    operating_expense_lines = _lines_for(PnlBehavior.OPERATING_EXPENSE, totals, transaction_ids)
    total_revenue = sum(line.total_minor for line in revenue_lines)
    total_cogs = sum(line.total_minor for line in cogs_lines)
    total_operating_expenses = sum(line.total_minor for line in operating_expense_lines)
    gross_profit = total_revenue - total_cogs
    return ProfitAndLoss(
        start_date=start_date,
        end_date=end_date,
        revenue_lines=revenue_lines,
        cogs_lines=cogs_lines,
        operating_expense_lines=operating_expense_lines,
        total_revenue_minor=total_revenue,
        total_cogs_minor=total_cogs,
        gross_profit_minor=gross_profit,
        total_operating_expenses_minor=total_operating_expenses,
        net_profit_minor=gross_profit - total_operating_expenses,
    )
