"""QBO P&L report normalization and zero-tolerance reconciliation behavior."""

import pytest

from app.services.reconciliation import parse_qbo_pnl, reconcile


def _qbo_account_payload(amount: object) -> dict[str, object]:
    return {
        "Rows": {
            "Row": [
                {
                    "ColData": [
                        {"value": "4000 Repair Service Revenue"},
                        {"value": amount},
                    ]
                }
            ]
        }
    }


def test_reconciliation_treats_one_cent_as_a_difference() -> None:
    """Permitting a one-cent tolerance would violate the exact reconciliation gate."""
    internal = {"4000": 100}
    qbo = parse_qbo_pnl(
        {
            "Rows": {
                "Row": [
                    {
                        "ColData": [
                            {"value": "4000 Repair Service Revenue"},
                            {"value": "0.99"},
                        ]
                    }
                ]
            }
        }
    )

    run = reconcile(internal, qbo)

    assert run.lines[0].account_number == "4000"
    assert run.lines[0].difference_minor == 1
    assert run.status.value == "differences"


def test_parser_recurses_sections_maps_numeric_account_fields_and_freezes_snapshot() -> None:
    """Ignoring QBO's numeric AccountNumber field would silently omit an account."""
    report = parse_qbo_pnl(
        {
            "Rows": {
                "Row": [
                    {
                        "type": "Section",
                        "Rows": {
                            "Row": [
                                {
                                    "AccountNumber": 4000,
                                    "ColData": [
                                        {"value": "QBO display label"},
                                        {"value": "10.00"},
                                    ],
                                },
                                {
                                    "ColData": [
                                        {"value": "Payroll Expense"},
                                        {"value": "(2.50)"},
                                    ],
                                },
                                {
                                    "ColData": [
                                        {"value": "Net Income"},
                                        {"value": "7.50"},
                                    ],
                                },
                            ]
                        },
                    }
                ]
            }
        }
    )

    assert dict(report.account_totals) == {"4000": 1000, "6000": -250}
    assert report.net_profit_minor == 750
    try:
        report.raw_snapshot["Rows"]["Row"] = ()
    except TypeError:
        pass
    else:
        raise AssertionError("raw QBO snapshot must be immutable")


@pytest.mark.parametrize(
    ("amount", "expected_cents"),
    [
        (None, 0),
        ("", 0),
        ("1,234.56", 123456),
        ("-35.00", -3500),
        ("(35.00)", -3500),
    ],
)
def test_parser_accepts_only_supported_exact_cent_money_values(
    amount: object, expected_cents: int
) -> None:
    """Valid QBO money strings must remain exact cents, including empty values."""
    report = parse_qbo_pnl(_qbo_account_payload(amount))

    assert report.account_totals["4000"] == expected_cents


@pytest.mark.parametrize(
    ("amount", "error_type"),
    [
        ("12.345", ValueError),
        (12.34, TypeError),
        (True, TypeError),
        ("not-money", ValueError),
        ("(35.00", ValueError),
        ("35.00)", ValueError),
        ("$1,23.45", ValueError),
    ],
)
def test_parser_rejects_invalid_or_non_exact_money_values(
    amount: object, error_type: type[Exception]
) -> None:
    """Rounding or silently skipping malformed QBO money would hide a reconciliation defect."""
    with pytest.raises(error_type):
        parse_qbo_pnl(_qbo_account_payload(amount))


def test_parser_rejects_duplicate_account_summary_rows() -> None:
    payload = {
        "Rows": {
            "Row": [
                {
                    "ColData": [
                        {"value": "4000 Repair Service Revenue"},
                        {"value": "10.00"},
                    ]
                },
                {
                    "ColData": [
                        {"value": "4000 Repair Service Revenue"},
                        {"value": "5.00"},
                    ]
                },
            ]
        }
    }

    with pytest.raises(ValueError, match="duplicate QBO P&L account"):
        parse_qbo_pnl(payload)


@pytest.mark.parametrize(
    "row",
    [
        {
            "ColData": [
                {"value": "9999 Unexpected Revenue"},
                {"value": "10.00"},
            ]
        },
        {
            "type": "Data",
            "ColData": [
                {"value": "Unexpected Revenue"},
                {"value": "10.00"},
            ],
        },
        {
            "AccountNumber": "9999",
            "ColData": [
                {"value": "Unexpected Revenue"},
                {"value": "10.00"},
            ],
        },
    ],
)
def test_parser_rejects_unmapped_qbo_account_rows(row: dict[str, object]) -> None:
    payload = {"Rows": {"Row": [row]}}

    with pytest.raises(ValueError, match="unmapped QBO P&L account"):
        parse_qbo_pnl(payload)


def test_parser_validates_qbo_report_scope_when_expected_period_is_supplied() -> None:
    payload = {
        **_qbo_account_payload("10.00"),
        "Header": {
            "ReportName": "ProfitAndLoss",
            "ReportBasis": "Cash",
            "StartPeriod": "2026-04-01",
            "EndPeriod": "2026-06-30",
            "Currency": "USD",
        },
    }

    report = parse_qbo_pnl(
        payload,
        expected_start_date="2026-04-01",
        expected_end_date="2026-06-30",
        require_cash=True,
    )

    assert report.account_totals["4000"] == 1000


def test_parser_accepts_real_qbo_empty_cash_report_shape() -> None:
    payload = {
        "Header": {
            "ReportName": "ProfitAndLoss",
            "ReportBasis": "Cash",
            "StartPeriod": "2026-04-01",
            "EndPeriod": "2026-06-30",
            "Currency": "USD",
            "AccountingStandard": "GAAP",
            "NoReportData": True,
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "group": "Income",
                    "Summary": {"ColData": [{"value": "Total Income"}]},
                },
                {
                    "type": "Section",
                    "group": "NetIncome",
                    "Summary": {"ColData": [{"value": "Net Income"}]},
                },
            ]
        },
    }

    report = parse_qbo_pnl(
        payload,
        expected_start_date="2026-04-01",
        expected_end_date="2026-06-30",
        require_cash=True,
    )

    assert report.no_report_data is True
    assert report.account_totals == {}
    assert report.net_profit_minor == 0


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ({}, "Header"),
        (
            {
                "ReportName": "ProfitAndLoss",
                "ReportBasis": "Accrual",
                "StartPeriod": "2026-04-01",
                "EndPeriod": "2026-06-30",
                "Currency": "USD",
            },
            "Cash",
        ),
        (
            {
                "ReportName": "ProfitAndLoss",
                "ReportBasis": "Cash",
                "StartPeriod": "2026-04-02",
                "EndPeriod": "2026-06-30",
                "Currency": "USD",
            },
            "period",
        ),
        (
            {
                "ReportName": "ProfitAndLoss",
                "ReportBasis": "Cash",
                "StartPeriod": "2026-04-01",
                "EndPeriod": "2026-06-30",
                "Currency": "CAD",
            },
            "USD",
        ),
    ],
)
def test_parser_rejects_wrong_or_missing_qbo_report_scope(
    header: dict[str, object], message: str
) -> None:
    payload = {**_qbo_account_payload("10.00"), "Header": header}

    with pytest.raises(ValueError, match=message):
        parse_qbo_pnl(
            payload,
            expected_start_date="2026-04-01",
            expected_end_date="2026-06-30",
            require_cash=True,
        )
