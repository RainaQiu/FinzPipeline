"""Immutable, data-driven deterministic accounting rule definitions."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.domain.classification import TransactionType
from app.domain.transactions import Direction


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: str
    account_number: str
    transaction_type: TransactionType
    keywords: tuple[str, ...]
    direction: Direction | None = None
    requires_review: bool = False
    match_all_keywords: bool = False

    def matches(self, description: str, direction: Direction) -> bool:
        if self.direction is not None and self.direction is not direction:
            return False
        normalized = description.upper()
        matcher = all if self.match_all_keywords else any
        return matcher(_contains_keyword(normalized, keyword) for keyword in self.keywords)


def _contains_keyword(description: str, keyword: str) -> bool:
    """Match merchant words/phrases, never a coincidental substring in another word."""
    return re.search(rf"(?<![A-Z0-9]){re.escape(keyword)}(?![A-Z0-9])", description) is not None


# Ordering is explicit precedence within the hard-rule tier.  Keep all merchant
# vocabulary here rather than dispersing it across service/API code.
RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition("owner_capital", "3000", TransactionType.OWNER_ACTIVITY, ("OWNER CAPITAL",), Direction.INFLOW, requires_review=True),
    RuleDefinition("owner_draw", "3000", TransactionType.OWNER_ACTIVITY, ("OWNER DRAW", "OWNER DISTRIBUTION"), Direction.OUTFLOW, requires_review=True),
    RuleDefinition("customer_refund", "4100", TransactionType.REFUND, ("REFUND TO",), Direction.OUTFLOW, requires_review=True),
    RuleDefinition("commercial_tool_package", "1500", TransactionType.FIXED_ASSET, ("COMMERCIAL TOOL PACKAGE",), Direction.OUTFLOW, requires_review=True),
    RuleDefinition("maintenance_plan_revenue", "4020", TransactionType.REVENUE, ("MAINT", "SERVICE PLAN"), Direction.INFLOW),
    RuleDefinition("installation_revenue", "4010", TransactionType.REVENUE, ("INSTALL",), Direction.INFLOW),
    RuleDefinition("materials_supplies", "5000", TransactionType.COGS, ("HOMEDEPOT", "HOME DEPOT", "LOWE", "LOWES", "FERGUSON", "SUPPLYHOUSE", "GRAINGER", "ABC PLUMBING SUPPLY", "CES"), Direction.OUTFLOW),
    RuleDefinition("subcontractors", "5010", TransactionType.COGS, ("RIVERA", "APEX", "NORTHLINE", "PRECISION INSTALL", "METRO HANDYMAN"), Direction.OUTFLOW),
    RuleDefinition("payroll", "6000", TransactionType.OPERATING_EXPENSE, ("ADP",), Direction.OUTFLOW),
    RuleDefinition("rent", "6010", TransactionType.OPERATING_EXPENSE, ("RENT",), Direction.OUTFLOW),
    RuleDefinition("fuel", "6020", TransactionType.OPERATING_EXPENSE, ("FUEL", "SHELL OIL", "BP", "EXXONMOBIL", "SPEEDWAY"), Direction.OUTFLOW),
    RuleDefinition("software_subscriptions", "6030", TransactionType.OPERATING_EXPENSE, ("QUICKBOOKS", "WORKSPACE", "SERVICETITAN"), Direction.OUTFLOW),
    RuleDefinition("advertising", "6040", TransactionType.OPERATING_EXPENSE, ("GOOGLE ADS", "YELP"), Direction.OUTFLOW),
    RuleDefinition("insurance", "6050", TransactionType.OPERATING_EXPENSE, ("HISCOX",), Direction.OUTFLOW),
    RuleDefinition("utilities", "6060", TransactionType.OPERATING_EXPENSE, ("CON EDISON", "VERIZON"), Direction.OUTFLOW),
    RuleDefinition("professional_fees", "6070", TransactionType.OPERATING_EXPENSE, ("CPA", "PROFESSIONAL"), Direction.OUTFLOW),
    RuleDefinition("bank_fees", "6080", TransactionType.OPERATING_EXPENSE, ("MONTHLY SERVICE FEE",), Direction.OUTFLOW),
    RuleDefinition("office_general", "6090", TransactionType.OPERATING_EXPENSE, ("STAPLES", "OFFICE SUPPLIES"), Direction.OUTFLOW),
    RuleDefinition("vehicle_repair", "6100", TransactionType.OPERATING_EXPENSE, ("FLEET AUTO CARE", "VEHICLE REPAIR"), Direction.OUTFLOW),
)
