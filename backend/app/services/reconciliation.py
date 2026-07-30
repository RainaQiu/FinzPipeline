"""QBO P&L normalization and exact zero-tolerance reconciliation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable, Mapping

from app.domain.accounting import (
    ProfitAndLoss,
    QboProfitAndLoss,
    ReconciliationLine,
    ReconciliationRun,
    ReconciliationStatus,
)
from app.domain.accounts import ACCOUNT_DEFINITIONS


_ACCOUNT_PREFIX = re.compile(r"^\s*(\d{4})(?:\D|$)")
_NET_PROFIT_NAMES = frozenset({"net income", "net profit"})
_MONEY = re.compile(
    r"^(?P<negative>-)?\$?(?P<whole>0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)(?:\.\d{2})?$"
)


def _amount_to_cents(value: object) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("QBO P&L amount must be an exact string or integer")
    if not isinstance(value, (str, int)):
        raise TypeError("QBO P&L amount must be an exact string or integer")
    text = str(value).strip()
    if not text:
        return 0
    parenthetical_negative = text.startswith("(")
    if parenthetical_negative != text.endswith(")"):
        raise ValueError(f"Invalid QBO P&L amount: {value!r}")
    normalized = text[1:-1] if parenthetical_negative else text
    match = _MONEY.fullmatch(normalized)
    if match is None or (parenthetical_negative and match.group("negative") is not None):
        raise ValueError(f"Invalid QBO P&L amount: {value!r}")
    try:
        cents = int(Decimal(normalized.replace("$", "").replace(",", "")) * 100)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid QBO P&L amount: {value!r}") from exc
    return -cents if parenthetical_negative and cents > 0 else cents


def _account_number(row: Mapping[str, object], label: str) -> str | None:
    for key in ("account_number", "AccountNumber", "accountNumber"):
        value = row.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            number = str(value)
            if number in ACCOUNT_DEFINITIONS:
                return number
    match = _ACCOUNT_PREFIX.match(label)
    if match and match.group(1) in ACCOUNT_DEFINITIONS:
        return match.group(1)
    normalized_label = label.strip().casefold()
    for number, account in ACCOUNT_DEFINITIONS.items():
        if normalized_label == account.name.casefold():
            return number
    return None


def _row_label_and_amount(row: Mapping[str, object]) -> tuple[str, int] | None:
    col_data = row.get("ColData")
    if not isinstance(col_data, list) or not col_data:
        return None
    values = [column.get("value", "") for column in col_data if isinstance(column, Mapping)]
    if not values:
        return None
    label = str(values[0])
    amount_value = values[-1] if len(values) > 1 else row.get("amount", row.get("Amount", ""))
    return label, _amount_to_cents(amount_value)


def _is_account_row(row: Mapping[str, object], label: str) -> bool:
    if any(key in row for key in ("account_number", "AccountNumber", "accountNumber")):
        return True
    if str(row.get("type", "")).casefold() == "data":
        return True
    return _ACCOUNT_PREFIX.match(label) is not None


def _iter_rows(value: object) -> Iterable[Mapping[str, object]]:
    if isinstance(value, Mapping):
        if "ColData" in value:
            yield value
        for child in value.values():
            yield from _iter_rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_rows(child)


def _iso_date(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else value


def _validate_report_scope(
    payload: Mapping[str, object],
    *,
    expected_start_date: date | str,
    expected_end_date: date | str,
    require_cash: bool,
) -> None:
    header = payload.get("Header")
    if not isinstance(header, Mapping) or not header:
        raise ValueError("QBO P&L Header is required for scoped reconciliation")
    if str(header.get("ReportName", "")).casefold() != "profitandloss":
        raise ValueError("QBO report must be ProfitAndLoss")
    if require_cash and str(header.get("ReportBasis", "")).casefold() != "cash":
        raise ValueError("QBO P&L must use Cash report basis")
    actual_period = (header.get("StartPeriod"), header.get("EndPeriod"))
    expected_period = (_iso_date(expected_start_date), _iso_date(expected_end_date))
    if actual_period != expected_period:
        raise ValueError("QBO P&L report period does not match the reconciliation period")
    if str(header.get("Currency", "")).upper() != "USD":
        raise ValueError("QBO P&L report currency must be USD")


def parse_qbo_pnl(
    payload: Mapping[str, object],
    *,
    expected_start_date: date | str | None = None,
    expected_end_date: date | str | None = None,
    require_cash: bool = False,
) -> QboProfitAndLoss:
    """Parse nested QBO rows without relying on report display order."""
    if (expected_start_date is None) != (expected_end_date is None):
        raise ValueError("both expected QBO P&L period dates are required")
    if expected_start_date is not None and expected_end_date is not None:
        _validate_report_scope(
            payload,
            expected_start_date=expected_start_date,
            expected_end_date=expected_end_date,
            require_cash=require_cash,
        )
    totals: dict[str, int] = {}
    net_profit: int | None = None
    for row in _iter_rows(payload.get("Rows", payload)):
        parsed = _row_label_and_amount(row)
        if parsed is None:
            continue
        label, amount = parsed
        account_number = _account_number(row, label)
        if account_number is not None:
            if account_number in totals:
                raise ValueError(
                    f"duplicate QBO P&L account summary: {account_number}"
                )
            totals[account_number] = amount
        elif label.strip().casefold() in _NET_PROFIT_NAMES:
            net_profit = amount
        elif _is_account_row(row, label):
            raise ValueError(f"unmapped QBO P&L account: {label}")
    return QboProfitAndLoss(
        account_totals=totals,
        raw_snapshot=payload,
        net_profit_minor=net_profit,
        no_report_data=bool(
            isinstance(payload.get("Header"), Mapping)
            and payload["Header"].get("NoReportData") is True
        ),
    )


def _internal_totals(internal: ProfitAndLoss | Mapping[str, int]) -> tuple[Mapping[str, int], int | None]:
    if isinstance(internal, ProfitAndLoss):
        return internal.account_totals, internal.net_profit_minor
    return internal, None


def _diagnostics(account_number: str, internal: int, qbo: int) -> tuple[str, ...]:
    if internal == qbo:
        return ()
    if internal and not qbo:
        return ("missing_in_qbo", "posted_internally_but_missing_in_qbo")
    if qbo and not internal:
        return ("excluded_internally_but_posted_to_qbo",)
    if internal == -qbo:
        return ("wrong_sign", "refund_mapped_incorrectly")
    return ("wrong_account", "wrong_period", "duplicate_qbo_post")


def reconcile(
    internal: ProfitAndLoss | Mapping[str, int], qbo: QboProfitAndLoss
) -> ReconciliationRun:
    """Compare normalized P&Ls with an exact, zero-cent tolerance."""
    internal_totals, internal_net = _internal_totals(internal)
    lines = []
    for account_number in sorted(set(internal_totals) | set(qbo.account_totals)):
        internal_minor = internal_totals.get(account_number, 0)
        qbo_minor = qbo.account_totals.get(account_number, 0)
        difference = internal_minor - qbo_minor
        status = ReconciliationStatus.MATCHED if difference == 0 else ReconciliationStatus.DIFFERENCES
        lines.append(
            ReconciliationLine(
                account_number=account_number,
                internal_minor=internal_minor,
                qbo_minor=qbo_minor,
                difference_minor=difference,
                status=status,
                diagnostic_candidates=_diagnostics(account_number, internal_minor, qbo_minor),
            )
        )
    if internal_net is not None or qbo.net_profit_minor is not None:
        internal_minor = internal_net or 0
        qbo_minor = qbo.net_profit_minor or 0
        difference = internal_minor - qbo_minor
        status = ReconciliationStatus.MATCHED if difference == 0 else ReconciliationStatus.DIFFERENCES
        lines.append(
            ReconciliationLine(
                account_number="net_profit",
                internal_minor=internal_minor,
                qbo_minor=qbo_minor,
                difference_minor=difference,
                status=status,
                diagnostic_candidates=_diagnostics("net_profit", internal_minor, qbo_minor),
            )
        )
    run_status = (
        ReconciliationStatus.MATCHED
        if all(line.status is ReconciliationStatus.MATCHED for line in lines)
        else ReconciliationStatus.DIFFERENCES
    )
    return ReconciliationRun(lines=tuple(lines), status=run_status)
