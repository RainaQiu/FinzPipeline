from datetime import date

from app.domain.transactions import Direction, NormalizedTransaction
from app.services.deduplication import DuplicateStatus, deduplicate


def tx(transaction_id: str, *, bank_id: str, raw_id: str, amount: int = 12500,
       account: str = "1000", description: str = "ACME SUPPLY",
       transaction_date: date = date(2026, 4, 1), posted_date: date = date(2026, 4, 1)) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction_id,
        raw_record_id=raw_id,
        bank_transaction_id=bank_id,
        transaction_date=transaction_date,
        posted_date=posted_date,
        description_original=description,
        description_normalized=description,
        amount_minor=amount,
        currency="USD",
        direction=Direction.INFLOW if amount > 0 else Direction.OUTFLOW,
        bank_account_number=account,
    )


def test_exact_same_bank_id_keeps_first_row_as_canonical_and_excludes_later_duplicate():
    """Changing the first-seen rule or business-field comparison would double-sync cash."""
    result = deduplicate([
        tx("first", bank_id="BF-1", raw_id="raw-1"),
        tx("second", bank_id="BF-1", raw_id="raw-2"),
    ])

    assert result.canonical_ids == ("first",)
    assert dict(result.duplicate_to_canonical) == {"second": "first"}
    assert result.status_by_id["first"] is DuplicateStatus.CANONICAL
    assert result.status_by_id["second"] is DuplicateStatus.DUPLICATE


def test_same_bank_id_with_changed_business_field_marks_every_row_conflict_without_canonical():
    """A reused bank ID with different money data must go to review, not be syncable."""
    result = deduplicate([
        tx("first", bank_id="BF-2", raw_id="raw-1"),
        tx("second", bank_id="BF-2", raw_id="raw-2", amount=12600),
    ])

    assert result.canonical_ids == ()
    assert tuple(transaction.id for transaction in result.conflicts) == ("first", "second")
    assert result.status_by_id == {
        "first": DuplicateStatus.CONFLICT,
        "second": DuplicateStatus.CONFLICT,
    }


def test_similar_different_bank_ids_are_marked_possible_without_exclusion():
    """Removing a similar same-account payment would hide a transaction without proof."""
    result = deduplicate([
        tx("first", bank_id="BF-3", raw_id="raw-1", description="ACME OFFICE SUPPLY"),
        tx(
            "second",
            bank_id="BF-4",
            raw_id="raw-2",
            description="ACME OFFICE SUPPLY",
            transaction_date=date(2026, 4, 2),
            posted_date=date(2026, 4, 2),
        ),
    ])

    assert result.canonical_ids == ("first", "second")
    assert tuple(transaction.id for transaction in result.possible_duplicates) == ("first", "second")
    assert result.status_by_id["first"] is DuplicateStatus.POSSIBLE_DUPLICATE
    assert result.status_by_id["second"] is DuplicateStatus.POSSIBLE_DUPLICATE
