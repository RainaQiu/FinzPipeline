"""Deterministic conversion of immutable source rows into bank transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from hashlib import sha256
import re

from app.domain.transactions import Direction, NormalizedTransaction, RawRecord


_CENT = Decimal("0.01")
_EXCEL_EPOCH = date(1899, 12, 30)
_BANK_ACCOUNTS = {"Operating Checking": "1000", "Tax Reserve": "1010"}
_CURRENCY_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
_CURRENCY_STRING = re.compile(
    rf"(?:\(\$?{_CURRENCY_NUMBER}\)|-?\$?{_CURRENCY_NUMBER})\Z"
)


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    transaction_id: str
    transaction_date: str
    posted_date: str
    description: str
    amount: str
    currency: str
    bank_account: str


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    raw_record_id: str
    transaction: NormalizedTransaction | None
    issues: tuple[QualityIssue, ...]


def parse_amount_minor(value: object) -> int:
    """Parse an exact USD amount into integer cents without binary floating point."""
    if isinstance(value, bool):
        raise TypeError("amount must not be a boolean")
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        raise TypeError("amount must not be a float")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, str):
        decimal_value = _parse_currency_string(value)
    else:
        raise TypeError("amount must be an integer, Decimal, or currency string")

    if not decimal_value.is_finite():
        raise ValueError("amount must be finite")
    if decimal_value.as_tuple().exponent < -2:
        raise ValueError("amount must have at most two decimal places")
    return int(decimal_value * 100)


def _parse_currency_string(value: str) -> Decimal:
    text = value.strip()
    parenthesized = text.startswith("(") and text.endswith(")")
    if not _CURRENCY_STRING.fullmatch(text):
        raise ValueError("amount is invalid")
    if parenthesized:
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("amount is invalid") from error
    return -parsed if parenthesized else parsed


def parse_transaction_date(value: object) -> date:
    """Normalize date, datetime, ISO text, or Excel's integer date serial."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        raise TypeError("date must not be a boolean")
    if isinstance(value, int):
        try:
            return _EXCEL_EPOCH + timedelta(days=value)
        except OverflowError as error:
            raise ValueError("Excel date serial is out of range") from error
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("date is empty")
        try:
            return date.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
            except ValueError as error:
                raise ValueError("date must be ISO formatted") from error
    raise TypeError("date must be a date, datetime, ISO string, or Excel serial")


def normalize_record(raw: RawRecord, mapping: ColumnMapping) -> NormalizationResult:
    """Return a complete transaction or every source-quality issue for one raw row."""
    values = raw.raw_values
    issues: list[QualityIssue] = []

    bank_transaction_id = _required_text(values.get(mapping.transaction_id))
    if bank_transaction_id is None:
        issues.append(_issue("MISSING_TRANSACTION_ID", "Transaction ID is required", mapping.transaction_id))

    transaction_date = _parse_required_date(
        values.get(mapping.transaction_date), mapping.transaction_date, "TRANSACTION_DATE", issues
    )
    posted_value = values.get(mapping.posted_date)
    posted_date = transaction_date if _is_missing(posted_value) else _parse_optional_date(
        posted_value, mapping.posted_date, "POSTED_DATE", issues
    )

    amount = _parse_required_amount(values.get(mapping.amount), mapping.amount, issues)
    if amount == 0:
        issues.append(_issue("ZERO_AMOUNT", "Amount must not be zero", mapping.amount))

    currency_value = _required_text(values.get(mapping.currency))
    currency = currency_value.upper() if currency_value is not None else None
    if currency != "USD":
        issues.append(_issue("UNSUPPORTED_CURRENCY", "Only USD transactions are supported", mapping.currency))

    bank_name = _required_text(values.get(mapping.bank_account))
    bank_account_number = _BANK_ACCOUNTS.get(bank_name) if bank_name is not None else None
    if bank_account_number is None:
        issues.append(_issue("UNKNOWN_BANK_ACCOUNT", "Bank account is not mapped", mapping.bank_account))

    description_original = _description(values.get(mapping.description))
    description_normalized = re.sub(r"\s+", " ", description_original.strip()).upper()

    if issues:
        return NormalizationResult(raw.id, None, tuple(issues))

    assert bank_transaction_id is not None
    assert transaction_date is not None
    assert posted_date is not None
    assert amount is not None
    assert currency == "USD"
    assert bank_account_number is not None
    transaction_id = _transaction_id(
        raw_record_id=raw.id,
        bank_transaction_id=bank_transaction_id,
        transaction_date=transaction_date,
        posted_date=posted_date,
        description_normalized=description_normalized,
        amount_minor=amount,
        currency=currency,
        bank_account_number=bank_account_number,
    )
    return NormalizationResult(
        raw.id,
        NormalizedTransaction(
            id=transaction_id,
            raw_record_id=raw.id,
            bank_transaction_id=bank_transaction_id,
            transaction_date=transaction_date,
            posted_date=posted_date,
            description_original=description_original,
            description_normalized=description_normalized,
            amount_minor=amount,
            currency="USD",
            direction=Direction.INFLOW if amount > 0 else Direction.OUTFLOW,
            bank_account_number=bank_account_number,
        ),
        (),
    )


def _parse_required_date(
    value: object, field: str, code_part: str, issues: list[QualityIssue]
) -> date | None:
    if _is_missing(value):
        issues.append(_issue(f"MISSING_{code_part}", f"{code_part.replace('_', ' ').title()} is required", field))
        return None
    return _parse_optional_date(value, field, code_part, issues)


def _parse_optional_date(
    value: object, field: str, code_part: str, issues: list[QualityIssue]
) -> date | None:
    try:
        return parse_transaction_date(value)
    except (TypeError, ValueError):
        issues.append(_issue(f"INVALID_{code_part}", f"{code_part.replace('_', ' ').title()} is invalid", field))
        return None


def _parse_required_amount(value: object, field: str, issues: list[QualityIssue]) -> int | None:
    if _is_missing(value):
        issues.append(_issue("MISSING_AMOUNT", "Amount is required", field))
        return None
    try:
        return parse_amount_minor(value)
    except (TypeError, ValueError):
        issues.append(_issue("INVALID_AMOUNT", "Amount is invalid", field))
        return None


def _required_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _description(value: object) -> str:
    return "" if value is None else str(value)


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _issue(code: str, message: str, field: str | None) -> QualityIssue:
    return QualityIssue(code=code, message=message, field=field)


def _transaction_id(
    *,
    raw_record_id: str,
    bank_transaction_id: str,
    transaction_date: date,
    posted_date: date,
    description_normalized: str,
    amount_minor: int,
    currency: str,
    bank_account_number: str,
) -> str:
    payload = {
        "amount_minor": amount_minor,
        "bank_account_number": bank_account_number,
        "bank_transaction_id": bank_transaction_id,
        "currency": currency,
        "description_normalized": description_normalized,
        "posted_date": posted_date.isoformat(),
        "raw_record_id": raw_record_id,
        "transaction_date": transaction_date.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()
