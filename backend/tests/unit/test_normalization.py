from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.domain.transactions import Direction, RawRecord
from app.services.normalization import (
    ColumnMapping,
    normalize_record,
    parse_amount_minor,
    parse_transaction_date,
)


MAPPING = ColumnMapping(
    transaction_id="Transaction ID",
    transaction_date="Transaction Date",
    posted_date="Posted Date",
    description="Description",
    amount="Amount",
    currency="Currency",
    bank_account="Bank Account",
)


def make_raw_record(raw_values: dict[str, object]) -> RawRecord:
    return RawRecord(
        id="raw-001",
        source_filename="checking.csv",
        source_file_sha256="a" * 64,
        source_sheet="Transactions",
        source_row_number=2,
        raw_values=raw_values,
        raw_row_sha256="b" * 64,
        ingested_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("$3,425.00", 342500),
        ("($35.00)", -3500),
        ("-$35.00", -3500),
        (Decimal("-0.01"), -1),
        (42, 4200),
    ],
)
def test_parse_amount_minor_exactly(source: object, expected: int):
    """A wrong decimal conversion would misstate cash-basis accounting."""
    assert parse_amount_minor(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        True,
        False,
        3.5,
        Decimal("3.456"),
        "3.456",
        "NaN",
        "Infinity",
        "(-$35.00)",
        "(+$35.00)",
        "1,2",
        "$1$2",
        "12,34.00",
    ],
)
def test_parse_amount_minor_rejects_inexact_or_binary_values(source: object):
    """Float or non-finite values must never enter integer-cent accounting."""
    with pytest.raises((TypeError, ValueError)):
        parse_amount_minor(source)


@pytest.mark.parametrize("amount", ["(-$35.00)", "1,2", "$1$2", "12,34.00"])
def test_normalize_record_quarantines_malformed_currency_amounts(amount: str):
    """Ambiguous amount syntax must never become a signed integer-cent transaction."""
    raw = make_raw_record(
        {
            "Transaction ID": "bank-malformed-amount",
            "Transaction Date": "2026-04-01",
            "Posted Date": "2026-04-01",
            "Description": "Malformed amount",
            "Amount": amount,
            "Currency": "USD",
            "Bank Account": "Operating Checking",
        }
    )

    result = normalize_record(raw, MAPPING)

    assert result.transaction is None
    assert [(issue.code, issue.field) for issue in result.issues] == [
        ("INVALID_AMOUNT", "Amount")
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (date(2026, 4, 1), date(2026, 4, 1)),
        (datetime(2026, 4, 1, 9, 30, tzinfo=timezone.utc), date(2026, 4, 1)),
        ("2026-04-01", date(2026, 4, 1)),
        (46113, date(2026, 4, 1)),
    ],
)
def test_parse_transaction_date_accepts_supported_bank_encodings(source: object, expected: date):
    """Source-specific date encodings must normalize to the same calendar day."""
    assert parse_transaction_date(source) == expected


def test_parse_transaction_date_rejects_an_out_of_range_excel_serial():
    """An overflowing spreadsheet serial must be quarantined instead of wrapping dates."""
    with pytest.raises(ValueError):
        parse_transaction_date(10_000_000)


def test_normalize_record_builds_a_stable_transaction_with_preserved_description():
    """Changing whitespace cleanup or account mapping must not change raw lineage."""
    raw = make_raw_record(
        {
            "Transaction ID": "bank-900",
            "Transaction Date": "2026-04-01",
            "Posted Date": 46114,
            "Description": "  Acme   24/7   Repair  ",
            "Amount": "$3,425.00",
            "Currency": "USD",
            "Bank Account": "Operating Checking",
        }
    )

    result = normalize_record(raw, MAPPING)

    assert result.raw_record_id == "raw-001"
    assert result.issues == ()
    assert result.transaction is not None
    assert result.transaction.id == "0bc27e7416c41b1ed5884db2e230f5fc0af66ef805bcbdccf297be551cf97b72"
    assert result.transaction.raw_record_id == "raw-001"
    assert result.transaction.bank_transaction_id == "bank-900"
    assert result.transaction.transaction_date == date(2026, 4, 1)
    assert result.transaction.posted_date == date(2026, 4, 2)
    assert result.transaction.description_original == "  Acme   24/7   Repair  "
    assert result.transaction.description_normalized == "ACME 24/7 REPAIR"
    assert result.transaction.amount_minor == 342500
    assert result.transaction.currency == "USD"
    assert result.transaction.direction is Direction.INFLOW
    assert result.transaction.bank_account_number == "1000"


def test_normalize_record_maps_tax_reserve_and_negative_amount_to_outflow():
    """A negative tax-reserve entry must remain an outflow on account 1010."""
    raw = make_raw_record(
        {
            "Transaction ID": "bank-901",
            "Transaction Date": date(2026, 4, 3),
            "Posted Date": date(2026, 4, 3),
            "Description": "Tax payment",
            "Amount": "($35.00)",
            "Currency": "usd",
            "Bank Account": "Tax Reserve",
        }
    )

    result = normalize_record(raw, MAPPING)

    assert result.issues == ()
    assert result.transaction is not None
    assert result.transaction.amount_minor == -3500
    assert result.transaction.direction is Direction.OUTFLOW
    assert result.transaction.bank_account_number == "1010"


def test_normalize_record_quarantines_all_invalid_fields_without_losing_raw_record():
    """Independent source defects must accumulate so operators can correct one raw row."""
    raw = make_raw_record(
        {
            "Transaction ID": " ",
            "Transaction Date": "not-a-date",
            "Posted Date": "2026-04-01",
            "Description": "  19  ",
            "Amount": "3.456",
            "Currency": "CAD",
            "Bank Account": "Savings",
        }
    )

    result = normalize_record(raw, MAPPING)

    assert result.raw_record_id == "raw-001"
    assert result.transaction is None
    assert [(issue.code, issue.field) for issue in result.issues] == [
        ("MISSING_TRANSACTION_ID", "Transaction ID"),
        ("INVALID_TRANSACTION_DATE", "Transaction Date"),
        ("INVALID_AMOUNT", "Amount"),
        ("UNSUPPORTED_CURRENCY", "Currency"),
        ("UNKNOWN_BANK_ACCOUNT", "Bank Account"),
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("Transaction ID", None, "MISSING_TRANSACTION_ID"),
        ("Transaction Date", None, "MISSING_TRANSACTION_DATE"),
        ("Amount", None, "MISSING_AMOUNT"),
    ],
)
def test_normalize_record_quarantines_required_missing_fields(
    field: str, value: object, expected_code: str
):
    """A missing required source cell must prevent a partial transaction from being emitted."""
    values: dict[str, object] = {
        "Transaction ID": "bank-902",
        "Transaction Date": "2026-04-04",
        "Posted Date": "2026-04-04",
        "Description": "Part 10",
        "Amount": "$10.00",
        "Currency": "USD",
        "Bank Account": "Operating Checking",
    }
    values[field] = value

    result = normalize_record(make_raw_record(values), MAPPING)

    assert result.raw_record_id == "raw-001"
    assert result.transaction is None
    assert [(issue.code, issue.field) for issue in result.issues] == [(expected_code, field)]


def test_normalize_record_quarantines_zero_amount_explicitly():
    """Zero has no inflow/outflow direction and must not be silently classified."""
    raw = make_raw_record(
        {
            "Transaction ID": "bank-903",
            "Transaction Date": "2026-04-04",
            "Posted Date": "2026-04-04",
            "Description": "Zero test",
            "Amount": "$0.00",
            "Currency": "USD",
            "Bank Account": "Operating Checking",
        }
    )

    result = normalize_record(raw, MAPPING)

    assert result.transaction is None
    assert [(issue.code, issue.field) for issue in result.issues] == [("ZERO_AMOUNT", "Amount")]
