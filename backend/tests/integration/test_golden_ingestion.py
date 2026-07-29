"""Read-only verification of the supplied Finz challenge workbook."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone

from app.services.ingestion import ingest_rows, inspect_workbook
from app.services.deduplication import deduplicate
from app.services.transfers import match_transfers
from app.domain.accounts import ACCOUNT_DEFINITIONS
from app.domain.classification import ApprovalStatus, DecisionSource, TransactionType
from app.services.classification import ClassificationContext, classify_transaction
from app.services.pnl import build_pnl
from tests.fixtures.golden_dataset import (
    BRIGHTFIX_MAPPING,
    DATASET_NAME,
    EXPECTED_CANONICAL_RECORDS_BY_MONTH,
    EXPECTED_CLASSIFIED_ACCOUNT_TOTALS,
    EXPECTED_PNL_ACCOUNT_TOTALS_BY_MONTH,
    EXPECTED_PNL_TOTALS_BY_PERIOD,
    EXPECTED_DUPLICATE_EXTRAS,
    EXPECTED_DUPLICATE_TO_CANONICAL,
    EXPECTED_RAW_RECORDS,
    EXPECTED_SHEETS,
    EXPECTED_SOURCE_SHA256,
    EXPECTED_TRANSFER_PAIR_AMOUNTS,
    EXPECTED_UNIQUE_BANK_TRANSACTION_IDS,
    dataset_bytes,
    source_sha256,
)


def test_challenge_workbook_ingests_with_expected_lineage_and_counts():
    """The golden workbook is read-only and every expected input row is retained."""
    before_hash = source_sha256()
    data = dataset_bytes()

    inspection = inspect_workbook(data)
    batch = ingest_rows(data, DATASET_NAME, BRIGHTFIX_MAPPING)

    assert before_hash == EXPECTED_SOURCE_SHA256
    assert source_sha256() == before_hash
    assert inspection.sheet_names == EXPECTED_SHEETS
    assert inspection.header_guesses["Raw Bank Transactions"][0].row_number == 4
    assert len(batch.raw_records) == EXPECTED_RAW_RECORDS
    assert batch.raw_records[0].source_sheet == "Raw Bank Transactions"
    assert batch.raw_records[0].source_row_number == 5
    assert batch.source_file_sha256 == before_hash

    bank_ids = [str(raw.raw_values["Bank Transaction ID"]) for raw in batch.raw_records]
    counts = Counter(bank_ids)
    assert len(counts) == EXPECTED_UNIQUE_BANK_TRANSACTION_IDS
    assert sum(count - 1 for count in counts.values()) == EXPECTED_DUPLICATE_EXTRAS

    canonical_months = Counter()
    seen_bank_ids: set[str] = set()
    for result in batch.normalization_results:
        transaction = result.transaction
        assert transaction is not None
        if transaction.bank_transaction_id not in seen_bank_ids:
            seen_bank_ids.add(transaction.bank_transaction_id)
            canonical_months[transaction.transaction_date.month] += 1
    assert dict(canonical_months) == EXPECTED_CANONICAL_RECORDS_BY_MONTH

    normalized = tuple(
        result.transaction for result in batch.normalization_results if result.transaction is not None
    )
    deduplication = deduplicate(normalized)
    transfers = match_transfers(deduplication.canonical_transactions)

    assert len(deduplication.canonical_transactions) == EXPECTED_UNIQUE_BANK_TRANSACTION_IDS
    assert dict(deduplication.duplicate_to_canonical) == EXPECTED_DUPLICATE_TO_CANONICAL
    assert len(deduplication.conflicts) == 0
    assert len(transfers.pairs) == 6
    assert tuple(pair.amount_minor for pair in transfers.pairs) == EXPECTED_TRANSFER_PAIR_AMOUNTS
    assert all(
        len(pair.transaction_ids) == 2
        and pair.amount_minor > 0
        and pair.status == "matched"
        for pair in transfers.pairs
    )
    by_id = {transaction.id: transaction for transaction in deduplication.canonical_transactions}
    assert all(
        by_id[pair.outflow_transaction_id].amount_minor == -pair.amount_minor
        and by_id[pair.inflow_transaction_id].amount_minor == pair.amount_minor
        for pair in transfers.pairs
    )


def test_challenge_pipeline_classifies_all_canonical_transactions_and_preserves_expected_totals():
    """A rule regression must not leave a canonical row unclassified or alter challenge totals."""
    batch = ingest_rows(dataset_bytes(), DATASET_NAME, BRIGHTFIX_MAPPING)
    normalized = tuple(
        result.transaction for result in batch.normalization_results if result.transaction is not None
    )
    canonical = deduplicate(normalized).canonical_transactions
    transfer_ids = frozenset(
        transaction_id
        for pair in match_transfers(canonical).pairs
        for transaction_id in pair.transaction_ids
    )
    decisions = {
        transaction.id: classify_transaction(
            transaction, ClassificationContext(matched_transfer_ids=transfer_ids)
        )
        for transaction in canonical
    }

    assert len(canonical) == 195
    assert len(decisions) == len(canonical)
    assert {decision.account_number for decision in decisions.values()} <= set(ACCOUNT_DEFINITIONS)
    assert sum(decision.transaction_type is TransactionType.TRANSFER for decision in decisions.values()) == 12
    assert sum(decision.transaction_type is TransactionType.OWNER_ACTIVITY for decision in decisions.values()) == 2
    assert sum(decision.transaction_type is TransactionType.REFUND for decision in decisions.values()) == 3
    assert sum(decision.transaction_type is TransactionType.FIXED_ASSET for decision in decisions.values()) == 1

    totals: Counter[str] = Counter()
    for transaction in canonical:
        decision = decisions[transaction.id]
        if decision.transaction_type is TransactionType.REVENUE:
            totals[decision.account_number] += transaction.amount_minor
        elif decision.transaction_type in {TransactionType.COGS, TransactionType.OPERATING_EXPENSE}:
            totals[decision.account_number] += abs(transaction.amount_minor)
        elif decision.transaction_type is TransactionType.REFUND:
            totals[decision.account_number] += transaction.amount_minor

    assert dict(totals) == EXPECTED_CLASSIFIED_ACCOUNT_TOTALS


def test_challenge_pnl_matches_independently_reviewed_monthly_account_totals() -> None:
    """Dropping an account drill-down count would make the P&L unauditable."""
    batch = ingest_rows(dataset_bytes(), DATASET_NAME, BRIGHTFIX_MAPPING)
    normalized = tuple(
        result.transaction for result in batch.normalization_results if result.transaction is not None
    )
    canonical = deduplicate(normalized).canonical_transactions
    transfer_ids = frozenset(
        transaction_id
        for pair in match_transfers(canonical).pairs
        for transaction_id in pair.transaction_ids
    )
    decisions = [
        classify_transaction(transaction, ClassificationContext(matched_transfer_ids=transfer_ids))
        for transaction in canonical
    ]
    approved = tuple(
        replace(
            decision,
            source=DecisionSource.HUMAN,
            approval_status=ApprovalStatus.APPROVED,
            needs_review=False,
            reviewed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        if decision.transaction_type is TransactionType.REFUND
        else decision
        for decision in decisions
    )

    reports = {
        (4, 4): build_pnl(canonical, approved, date(2026, 4, 1), date(2026, 4, 30)),
        (5, 5): build_pnl(canonical, approved, date(2026, 5, 1), date(2026, 5, 31)),
        (6, 6): build_pnl(canonical, approved, date(2026, 6, 1), date(2026, 6, 30)),
        (4, 6): build_pnl(canonical, approved, date(2026, 4, 1), date(2026, 6, 30)),
    }

    for period, report in reports.items():
        expected = EXPECTED_PNL_TOTALS_BY_PERIOD[period]
        assert report.total_revenue_minor == expected["revenue"]
        assert report.total_cogs_minor == expected["cogs"]
        assert report.gross_profit_minor == expected["gross"]
        assert report.total_operating_expenses_minor == expected["opex"]
        assert report.net_profit_minor == expected["net"]
        assert report.gross_profit_minor == report.total_revenue_minor - report.total_cogs_minor
        assert report.net_profit_minor == report.gross_profit_minor - report.total_operating_expenses_minor

    for month in (4, 5, 6):
        report = reports[(month, month)]
        assert dict(report.account_totals) == EXPECTED_PNL_ACCOUNT_TOTALS_BY_MONTH[month]
        assert sum(line.count for line in report.revenue_lines) > 0
