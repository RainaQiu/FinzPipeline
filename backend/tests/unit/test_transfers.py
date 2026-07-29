from datetime import date

import pytest

from app.domain.transactions import Direction, NormalizedTransaction
from app.services.transfers import match_transfers


def tx(transaction_id: str, *, account: str, amount: int, description: str,
       transaction_date: date = date(2026, 4, 1)) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction_id,
        raw_record_id=f"raw-{transaction_id}",
        bank_transaction_id=f"bank-{transaction_id}",
        transaction_date=transaction_date,
        posted_date=transaction_date,
        description_original=description,
        description_normalized=description,
        amount_minor=amount,
        currency="USD",
        direction=Direction.INFLOW if amount > 0 else Direction.OUTFLOW,
        bank_account_number=account,
    )


def test_opposite_account_equal_transfer_with_same_reference_creates_one_deterministic_pair():
    """Breaking account, sign, amount, reference, or ID determinism could create two cash events."""
    outflow = tx("out", account="1000", amount=-500000, description="TRANSFER TO TAX RESERVE REF APR-1")
    inflow = tx(
        "in",
        account="1010",
        amount=500000,
        description="TRANSFER FROM OPERATING REF APR-1",
        transaction_date=date(2026, 4, 2),
    )

    result = match_transfers([inflow, outflow])

    assert len(result.pairs) == 1
    pair = result.pairs[0]
    assert pair.transaction_ids == ("out", "in")
    assert pair.amount_minor == 500000
    assert pair.date_distance_days == 1
    assert pair.match_method == "reference_and_amount"
    assert pair.status == "matched"
    assert len(pair.id) == 64
    assert match_transfers([outflow, inflow]).pairs[0].id == pair.id


def test_one_outflow_with_two_equally_valid_inflows_needs_review_without_auto_pairing():
    """Choosing an arbitrary same-value leg would misstate which cash movement is internal."""
    result = match_transfers([
        tx("out", account="1000", amount=-500000, description="TRANSFER TO RESERVE"),
        tx("in-a", account="1010", amount=500000, description="TRANSFER FROM OPERATING"),
        tx("in-b", account="1010", amount=500000, description="TRANSFER FROM OPERATING"),
    ])

    assert result.pairs == ()
    assert result.needs_review == (("in-a", "in-b", "out"),)


@pytest.mark.parametrize(
    ("inflow_account", "inflow_amount", "inflow_description", "inflow_date"),
    [
        ("1000", 500000, "TRANSFER FROM OPERATING", date(2026, 4, 1)),
        ("1010", -500000, "TRANSFER FROM OPERATING", date(2026, 4, 1)),
        ("1010", 499999, "TRANSFER FROM OPERATING", date(2026, 4, 1)),
        ("1010", 500000, "PAYMENT FROM OPERATING", date(2026, 4, 1)),
        ("1010", 500000, "TRANSFER FROM OPERATING", date(2026, 4, 4)),
    ],
)
def test_transfer_match_requires_every_conservative_business_condition(
    inflow_account: str, inflow_amount: int, inflow_description: str, inflow_date: date
):
    """Relaxing account, sign, amount, marker, or date rules would fabricate an internal transfer."""
    result = match_transfers([
        tx("out", account="1000", amount=-500000, description="TRANSFER TO RESERVE"),
        tx(
            "in",
            account=inflow_account,
            amount=inflow_amount,
            description=inflow_description,
            transaction_date=inflow_date,
        ),
    ])

    assert result.pairs == ()
    assert result.needs_review == ()
