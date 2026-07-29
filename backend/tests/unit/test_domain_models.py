from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from app.domain.accounts import (
    ACCOUNT_DEFINITIONS,
    AccountType,
    PnlBehavior,
    parse_account,
)
from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.accounting import LedgerLine, OutboxItem, OutboxStatus, ProfitAndLoss
from app.domain.transactions import Direction, NormalizedTransaction, RawRecord


def test_account_whitelist_has_exactly_the_challenge_accounts():
    """Adding an unapproved account must not silently expand the accounting scope."""
    assert tuple(ACCOUNT_DEFINITIONS) == (
        "1000", "1010", "1500", "3000", "4000", "4010", "4020", "4100",
        "5000", "5010", "6000", "6010", "6020", "6030", "6040", "6050",
        "6060", "6070", "6080", "6090", "6100",
    )
    assert parse_account("4000").pnl_behavior is PnlBehavior.REVENUE
    with pytest.raises(ValueError):
        parse_account("9999")


def test_challenge_chart_of_accounts_has_exact_metadata():
    """A mislabeled account would put deterministic classification into the wrong bucket."""
    assert {
        number: (definition.name, definition.account_type, definition.pnl_behavior)
        for number, definition in ACCOUNT_DEFINITIONS.items()
    } == {
        "1000": ("Operating Checking", AccountType.ASSET, PnlBehavior.EXCLUDE),
        "1010": ("Tax Reserve", AccountType.ASSET, PnlBehavior.EXCLUDE),
        "1500": ("Tools & Equipment", AccountType.ASSET, PnlBehavior.EXCLUDE),
        "3000": ("Owner's Equity", AccountType.EQUITY, PnlBehavior.EXCLUDE),
        "4000": ("Repair Service Revenue", AccountType.REVENUE, PnlBehavior.REVENUE),
        "4010": ("Installation Revenue", AccountType.REVENUE, PnlBehavior.REVENUE),
        "4020": ("Maintenance Plan Revenue", AccountType.REVENUE, PnlBehavior.REVENUE),
        "4100": ("Customer Refunds", AccountType.CONTRA_REVENUE, PnlBehavior.REFUND),
        "5000": ("Materials & Supplies", AccountType.COST_OF_GOODS_SOLD, PnlBehavior.COST_OF_GOODS_SOLD),
        "5010": ("Subcontractor Costs", AccountType.COST_OF_GOODS_SOLD, PnlBehavior.COST_OF_GOODS_SOLD),
        "6000": ("Payroll Expense", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6010": ("Rent Expense", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6020": ("Vehicle & Fuel", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6030": ("Software & Subscriptions", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6040": ("Marketing & Advertising", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6050": ("Insurance Expense", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6060": ("Utilities", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6070": ("Professional Fees", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6080": ("Bank Fees", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6090": ("Office & General", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
        "6100": ("Repairs & Maintenance", AccountType.OPERATING_EXPENSE, PnlBehavior.OPERATING_EXPENSE),
    }


def test_raw_record_freezes_raw_values_and_lineage():
    """Mutating preserved source data after ingestion must be impossible."""
    record = RawRecord(
        id="raw-1",
        source_filename="source.xlsx",
        source_file_sha256="a" * 64,
        source_sheet="Transactions",
        source_row_number=5,
        raw_values={"Amount": "$10.00"},
        raw_row_sha256="b" * 64,
        ingested_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(TypeError):
        record.raw_values["Amount"] = "$11.00"
    with pytest.raises(FrozenInstanceError):
        record.source_sheet = "Changed"


def test_raw_record_freezes_nested_raw_values():
    """Mutable nested source cells must not bypass raw-record immutability."""
    record = RawRecord(
        id="raw-1",
        source_filename="source.xlsx",
        source_file_sha256="a" * 64,
        source_sheet="Transactions",
        source_row_number=5,
        raw_values={"Metadata": {"source": "bank"}},
        raw_row_sha256="b" * 64,
        ingested_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(TypeError):
        record.raw_values["Metadata"]["source"] = "changed"


def test_normalized_transaction_uses_integer_cents_not_float():
    """Accepting float amounts would introduce non-deterministic accounting values."""
    with pytest.raises(TypeError):
        NormalizedTransaction(
            id="tx-1",
            raw_record_id="raw-1",
            bank_transaction_id="bank-1",
            transaction_date=date(2026, 4, 1),
            posted_date=date(2026, 4, 2),
            description_original="Payment",
            description_normalized="payment",
            amount_minor=1.5,
            currency="USD",
            direction=Direction.OUTFLOW,
            bank_account_number="1000",
        )


def test_classification_decision_uses_shared_enum_values_and_whitelisted_account():
    """A decision cannot direct a transaction to an account outside the challenge chart."""
    decision = ClassificationDecision(
        id="decision-1",
        transaction_id="tx-1",
        account_number="6000",
        transaction_type=TransactionType.OPERATING_EXPENSE,
        source=DecisionSource.HARD_RULE,
        confidence_basis_points=10000,
        approval_status=ApprovalStatus.APPROVED,
        needs_review=False,
        explanation="Known operating expense.",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    assert decision.transaction_type.value == "operating_expense"
    assert decision.source.value == "hard_rule"
    assert decision.approval_status.value == "approved"
    assert decision.account_number == "6000"


def test_ledger_and_outbox_records_are_immutable_and_keep_cents_as_integers():
    """Changing a planned ledger/sync record would break the audit trail."""
    line = LedgerLine(
        id="line-1",
        transaction_id="tx-1",
        classification_decision_id="decision-1",
        account_number="4000",
        amount_minor=12500,
        transaction_date=date(2026, 4, 1),
    )
    item = OutboxItem(
        id="outbox-1",
        realm_id="realm-1",
        transaction_id="tx-1",
        classification_version=1,
        payload_kind="Deposit",
        payload={"amount_minor": 12500},
        status=OutboxStatus.PENDING,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    assert line.amount_minor == 12500
    with pytest.raises(FrozenInstanceError):
        item.status = OutboxStatus.SUCCEEDED
    with pytest.raises(TypeError):
        item.payload["amount_minor"] = 13000


def test_outbox_payload_freezes_nested_mapping_and_list_values():
    """Nested sync payload content must not be mutable after it enters the audit trail."""
    item = OutboxItem(
        id="outbox-1",
        realm_id="realm-1",
        transaction_id="tx-1",
        classification_version=1,
        payload_kind="Deposit",
        payload={"line": {"amount_minor": 12500}, "ids": ["tx-1"]},
        status=OutboxStatus.PENDING,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(TypeError):
        item.payload["line"]["amount_minor"] = 13000
    with pytest.raises(AttributeError):
        item.payload["ids"].append("tx-2")


def test_classification_enums_match_the_design_vocabulary():
    """Old vocabulary would let later services produce unsupported decision states."""
    assert {member.value for member in TransactionType} == {
        "revenue", "cogs", "operating_expense", "refund", "transfer",
        "owner_activity", "fixed_asset",
    }
    assert {member.value for member in DecisionSource} == {
        "hard_rule", "learned_rule", "merchant_rule", "ai", "human",
    }
    assert {member.value for member in ApprovalStatus} == {
        "suggested", "approved", "rejected", "superseded",
    }


def test_ai_decision_cannot_bypass_required_review():
    """A provider-only classification must remain a human-review suggestion."""
    with pytest.raises(ValueError):
        ClassificationDecision(
            id="decision-ai",
            transaction_id="tx-ai",
            account_number="6030",
            transaction_type=TransactionType.OPERATING_EXPENSE,
            source=DecisionSource.AI,
            confidence_basis_points=8700,
            approval_status=ApprovalStatus.APPROVED,
            needs_review=False,
            explanation="AI proposal.",
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )


def test_profit_and_loss_rejects_float_totals() -> None:
    """A float P&L total would make exact-cent reconciliation non-deterministic."""
    with pytest.raises(TypeError):
        ProfitAndLoss(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            revenue_lines=(),
            cogs_lines=(),
            operating_expense_lines=(),
            total_revenue_minor=1.5,
            total_cogs_minor=0,
            gross_profit_minor=0,
            total_operating_expenses_minor=0,
            net_profit_minor=0,
        )
