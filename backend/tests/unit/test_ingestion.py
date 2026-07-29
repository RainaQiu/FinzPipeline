"""Unit coverage for bounded, deterministic CSV/XLSX ingestion."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from io import BytesIO
import random
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from app.services.ingestion import (
    IngestionLimitError,
    IngestionMapping,
    UnsupportedFileError,
    ingest_rows,
    inspect_workbook,
)
from app.services.normalization import ColumnMapping


CSV_MAPPING = ColumnMapping(
    transaction_id="Bank ID",
    transaction_date="Date",
    posted_date="Posted",
    description="Memo",
    amount="Value",
    currency="Currency",
    bank_account="Account",
)


def _xlsx_bytes(rows: list[list[object]], *, sheet_name: str = "Imported") -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _xlsx_with_extra_members(entries: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO(_xlsx_bytes([["header"]]))
    with ZipFile(output, mode="a", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return output.getvalue()


def test_csv_column_mapping_is_independent_of_source_column_order():
    """A source export may reorder columns without changing immutable lineage."""
    data = (
        "Memo,Account,Value,Bank ID,Currency,Posted,Date\n"
        "Quarterly hosting,Operating Checking,($35.00),bank-1,USD,2026-04-02,2026-04-01\n"
    ).encode("utf-8")

    batch = ingest_rows(data, "checking.csv", CSV_MAPPING)

    assert batch.source_file_sha256 == sha256(data).hexdigest()
    assert batch.counts == {"raw_records": 1, "normalized": 1, "quarantined": 0}
    raw = batch.raw_records[0]
    assert raw.source_sheet == "CSV"
    assert raw.source_row_number == 2
    assert raw.raw_values["Bank ID"] == "bank-1"
    with pytest.raises(TypeError):
        raw.raw_values["Bank ID"] = "changed"
    assert batch.normalization_results[0].transaction is not None


def test_xlsx_mapping_uses_configured_sheet_and_header_row():
    """Preceding title rows must not become transaction data."""
    mapping = IngestionMapping(columns=CSV_MAPPING, sheet_name="Bank Export", header_row=4)
    data = _xlsx_bytes(
        [
            ["BrightFix export"],
            ["Confidential"],
            [],
            ["Value", "Memo", "Bank ID", "Date", "Posted", "Currency", "Account"],
            ["$10.00", "Invoice 101", "bank-101", date(2026, 4, 1), date(2026, 4, 2), "USD", "Operating Checking"],
        ],
        sheet_name="Bank Export",
    )

    batch = ingest_rows(data, "bank.xlsx", mapping)

    assert len(batch.raw_records) == 1
    assert batch.raw_records[0].source_sheet == "Bank Export"
    assert batch.raw_records[0].source_row_number == 5
    assert batch.raw_records[0].raw_values["Bank ID"] == "bank-101"


def test_xlsx_numeric_money_cell_is_converted_exactly_at_adapter_boundary():
    """Spreadsheet floats become exact decimals before domain normalization."""
    data = _xlsx_bytes(
        [
            ["Bank ID", "Date", "Posted", "Memo", "Value", "Currency", "Account"],
            [
                "bank-decimal",
                date(2026, 1, 2),
                date(2026, 1, 2),
                "Supplies",
                12.34,
                "USD",
                "Operating Checking",
            ],
        ]
    )

    batch = ingest_rows(data, "numeric-money.xlsx", CSV_MAPPING)

    result = batch.normalization_results[0]
    assert result.transaction is not None
    assert result.transaction.amount_minor == 1234
    assert str(batch.raw_records[0].raw_values["Value"]) == "12.34"


def test_hashes_are_deterministic_for_the_same_file_and_row():
    """Repeated processing of identical bytes must retain stable lineage identities."""
    data = (
        "Bank ID,Date,Posted,Memo,Value,Currency,Account\n"
        "bank-1,2026-04-01,2026-04-01,Invoice,$10.00,USD,Operating Checking\n"
    ).encode("utf-8")

    first = ingest_rows(data, "one.csv", CSV_MAPPING)
    second = ingest_rows(data, "two.csv", CSV_MAPPING)

    assert first.source_file_sha256 == second.source_file_sha256
    assert first.raw_records[0].raw_row_sha256 == second.raw_records[0].raw_row_sha256
    assert first.raw_records[0].id == second.raw_records[0].id


def test_workbook_inspection_lists_sheets_and_header_guesses_without_ingesting_rows():
    """Operators need bounded structural information before choosing a mapping."""
    data = _xlsx_bytes(
        [["Title"], ["Bank ID", "Date", "Posted", "Memo", "Value", "Currency", "Account"]],
        sheet_name="Bank Export",
    )

    inspection = inspect_workbook(data)

    assert inspection.sheet_names == ("Bank Export",)
    assert inspection.header_guesses["Bank Export"][0].row_number == 2
    assert inspection.header_guesses["Bank Export"][0].values[0] == "Bank ID"


@pytest.mark.parametrize(
    ("data", "filename", "error_type"),
    [
        (b"", "empty.csv", IngestionLimitError),
        (b"Bank ID\n", "bank.xlsm", UnsupportedFileError),
        (b"Bank ID\n", "bank.txt", UnsupportedFileError),
    ],
)
def test_ingestion_rejects_unsupported_or_empty_files(
    data: bytes, filename: str, error_type: type[Exception]
):
    """Unsupported and empty input must fail before raw records are produced."""
    with pytest.raises(error_type):
        ingest_rows(data, filename, CSV_MAPPING)


def test_ingestion_enforces_configured_row_limit():
    """A caller-supplied bound prevents an unexpectedly large import."""
    data = (
        "Bank ID,Date,Posted,Memo,Value,Currency,Account\n"
        "bank-1,2026-04-01,2026-04-01,One,$1.00,USD,Operating Checking\n"
        "bank-2,2026-04-02,2026-04-02,Two,$2.00,USD,Operating Checking\n"
    ).encode("utf-8")
    mapping = IngestionMapping(columns=CSV_MAPPING, max_rows=1)

    with pytest.raises(IngestionLimitError, match="row limit"):
        ingest_rows(data, "too-many.csv", mapping)


def test_ingestion_enforces_configured_column_limit():
    """Per-import column bounds apply to CSV headers before any rows are accepted."""
    data = (
        "Bank ID,Date,Posted,Memo,Value,Currency,Account,Unexpected\n"
        "bank-1,2026-04-01,2026-04-01,One,$1.00,USD,Operating Checking,extra\n"
    ).encode("utf-8")
    mapping = IngestionMapping(columns=CSV_MAPPING, max_columns=7)

    with pytest.raises(IngestionLimitError, match="column limit"):
        ingest_rows(data, "too-wide.csv", mapping)


def test_ingestion_preview_remains_the_workbook_inspection_contract():
    """Older callers may use the preview name while sharing one immutable structure."""
    import app.services.ingestion as ingestion

    assert ingestion.IngestionPreview is ingestion.WorkbookInspection


def test_xlsx_formula_text_is_preserved_as_untrusted_raw_input():
    """Formula cells must be retained literally, never evaluated during ingestion."""
    data = _xlsx_bytes(
        [
            ["Bank ID", "Date", "Posted", "Memo", "Value", "Currency", "Account"],
            ["bank-1", date(2026, 4, 1), date(2026, 4, 1), "=CONCAT(\"Invoice\", \" 1\")", "$1.00", "USD", "Operating Checking"],
        ]
    )

    batch = ingest_rows(data, "formula.xlsx", CSV_MAPPING)

    assert batch.raw_records[0].raw_values["Memo"] == '=CONCAT("Invoice", " 1")'


def test_xlsx_rejects_an_excessive_archive_member_count():
    """Thousands of ignored ZIP parts must not consume parser resources."""
    data = _xlsx_with_extra_members(
        [(f"custom/part-{index}.bin", b"") for index in range(2001)]
    )

    with pytest.raises(IngestionLimitError, match="member count"):
        inspect_workbook(data)


def test_xlsx_rejects_a_high_compression_ratio_member():
    """A tiny compressed member must not expand into an unbounded payload."""
    data = _xlsx_with_extra_members(
        [("custom/compression-bomb.bin", b"\x00" * (2 * 1024 * 1024))]
    )

    with pytest.raises(IngestionLimitError, match="compression ratio"):
        inspect_workbook(data)


def test_xlsx_rejects_an_oversized_single_archive_member():
    """One expanded part must remain bounded even when the archive is small."""
    random_block = random.Random(20260729).randbytes(4 * 1024 * 1024)
    data = _xlsx_with_extra_members(
        [
            (
                "custom/large-member.bin",
                random_block + b"\x00" * (29 * 1024 * 1024),
            )
        ]
    )

    with pytest.raises(IngestionLimitError, match="member size"):
        inspect_workbook(data)


def test_xlsx_rejects_excessive_total_expanded_size():
    """Several individually valid parts must still obey a total expansion cap."""
    random_block = random.Random(20260730).randbytes(512 * 1024)
    entries = [
        (
            f"custom/expanded-{index}.bin",
            random_block + b"\x00" * (15 * 1024 // 2 * 1024),
        )
        for index in range(9)
    ]
    data = _xlsx_with_extra_members(entries)

    with pytest.raises(IngestionLimitError, match="total expanded size"):
        inspect_workbook(data)
