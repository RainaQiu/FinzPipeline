from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class AccountType(StrEnum):
    ASSET = "asset"
    EQUITY = "equity"
    REVENUE = "revenue"
    CONTRA_REVENUE = "contra_revenue"
    COST_OF_GOODS_SOLD = "cost_of_goods_sold"
    OPERATING_EXPENSE = "operating_expense"


class PnlBehavior(StrEnum):
    EXCLUDE = "exclude"
    REVENUE = "revenue"
    REFUND = "refund"
    COST_OF_GOODS_SOLD = "cost_of_goods_sold"
    OPERATING_EXPENSE = "operating_expense"


@dataclass(frozen=True, slots=True)
class AccountDefinition:
    number: str
    name: str
    account_type: AccountType
    pnl_behavior: PnlBehavior


def _account(
    number: str,
    name: str,
    account_type: AccountType,
    pnl_behavior: PnlBehavior = PnlBehavior.EXCLUDE,
) -> AccountDefinition:
    return AccountDefinition(number, name, account_type, pnl_behavior)


ACCOUNT_DEFINITIONS: Mapping[str, AccountDefinition] = MappingProxyType(
    {
        "1000": _account("1000", "Operating Checking", AccountType.ASSET),
        "1010": _account("1010", "Tax Reserve", AccountType.ASSET),
        "1500": _account("1500", "Tools & Equipment", AccountType.ASSET),
        "3000": _account("3000", "Owner's Equity", AccountType.EQUITY),
        "4000": _account("4000", "Repair Service Revenue", AccountType.REVENUE, PnlBehavior.REVENUE),
        "4010": _account("4010", "Installation Revenue", AccountType.REVENUE, PnlBehavior.REVENUE),
        "4020": _account("4020", "Maintenance Plan Revenue", AccountType.REVENUE, PnlBehavior.REVENUE),
        "4100": _account("4100", "Customer Refunds", AccountType.CONTRA_REVENUE, PnlBehavior.REFUND),
        "5000": _account("5000", "Materials & Supplies", AccountType.COST_OF_GOODS_SOLD, PnlBehavior.COST_OF_GOODS_SOLD),
        "5010": _account("5010", "Subcontractor Costs", AccountType.COST_OF_GOODS_SOLD, PnlBehavior.COST_OF_GOODS_SOLD),
        "6000": _account("6000", "Payroll Expense", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6010": _account("6010", "Rent Expense", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6020": _account("6020", "Vehicle & Fuel", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6030": _account("6030", "Software & Subscriptions", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6040": _account("6040", "Marketing & Advertising", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6050": _account("6050", "Insurance Expense", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6060": _account("6060", "Utilities", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6070": _account("6070", "Professional Fees", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6080": _account("6080", "Bank Fees", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6090": _account("6090", "Office & General", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6100": _account("6100", "Repairs & Maintenance", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
    }
)


def parse_account(number: str) -> AccountDefinition:
    try:
        return ACCOUNT_DEFINITIONS[number]
    except KeyError as exc:
        raise ValueError(f"Unsupported account number: {number}") from exc
