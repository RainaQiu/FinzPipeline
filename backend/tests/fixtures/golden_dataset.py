"""Compact expectations for the supplied Finz challenge workbook."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from app.services.ingestion import IngestionMapping
from app.services.normalization import ColumnMapping


DATASET_NAME = "Finz Accounting Data Engineering Challenge Dataset.xlsx"
DATASET_PATH = Path(__file__).resolve().parents[3] / DATASET_NAME
EXPECTED_SOURCE_SHA256 = "b4a45dc35de632607e1475536113ffece11406429c7f0dc3b9b0ac89a05d3635"
EXPECTED_SHEETS = (
    "Company Setup",
    "QBO Chart of Accounts",
    "Raw Bank Transactions",
)
EXPECTED_RAW_RECORDS = 200
EXPECTED_UNIQUE_BANK_TRANSACTION_IDS = 195
EXPECTED_DUPLICATE_EXTRAS = 5
EXPECTED_CANONICAL_RECORDS_BY_MONTH = {4: 65, 5: 65, 6: 65}
EXPECTED_DUPLICATE_TO_CANONICAL = {
    "ebb3fac8b8de974b598bda0f0fda5e511121ccc4a81d7ba5e5bad1f45ea11ae9": "78fd9054a8cf158a684b30cd08e4833d988506bed9ca1faa12e7f7c6c9b28f12",
    "e5fc8833f87e82aa9e184b6e71c20cd2b9aaed0dc1aedd077a901a2d4a45cb6a": "aff0e0df89c122d4af2ca8064ec0a50a57e0b4740ff6a23dd234251ebb04755f",
    "ee6ea30adc55620ed5ed957783424ee266f728e2e416add0a7ca21d3b407f110": "f218f55be067c4f5428d2ebf561f96f70b1f06e80ea3e2cef938ded337bc2640",
    "f06b534c2d22d388f57fb6d44b6dd9387ac9a4fe37d8b26fe418bd0ebd5bcb83": "bb0b96c181642d52f27c5ca333d2efa671eb8bc4e390d8349f7ca981e76944cd",
    "d56fd81f7bc025691eb18f5e520b02678bd94cbeaa30e0c46e4b3c78046fa26e": "b98163832a0feecc033a9461582fca80f958a20cf6fc1b286f552f1afce73327",
}
EXPECTED_TRANSFER_PAIR_AMOUNTS = (900000, 800000, 600000, 700000, 700000, 500000)
EXPECTED_CLASSIFIED_ACCOUNT_TOTALS = {
    "4000": 18690000,
    "4010": 10745000,
    "4020": 1095000,
    "4100": -502500,
    "5000": 5105000,
    "5010": 4280000,
    "6000": 8025000,
    "6010": 2460000,
    "6020": 433500,
    "6030": 433500,
    "6040": 885000,
    "6050": 367500,
    "6060": 364500,
    "6070": 495000,
    "6080": 10500,
    "6090": 93000,
    "6100": 257000,
}

EXPECTED_PNL_ACCOUNT_TOTALS_BY_MONTH = {
    4: {
        "4000": 6227500, "4010": 3350000, "4020": 365000, "4100": -125000,
        "5000": 1502500, "5010": 1630000, "6000": 2580000, "6010": 820000,
        "6020": 148500, "6030": 144500, "6040": 280000, "6050": 122500,
        "6060": 117000, "6070": 165000, "6080": 3500, "6090": 31000, "6100": 74000,
    },
    5: {
        "4000": 6490000, "4010": 3970000, "4020": 365000, "4100": -167500,
        "5000": 1755000, "5010": 1450000, "6000": 2675000, "6010": 820000,
        "6020": 154500, "6030": 144500, "6040": 295000, "6050": 122500,
        "6060": 121500, "6070": 165000, "6080": 3500, "6090": 31000, "6100": 91500,
    },
    6: {
        "4000": 5972500, "4010": 3425000, "4020": 365000, "4100": -210000,
        "5000": 1847500, "5010": 1200000, "6000": 2770000, "6010": 820000,
        "6020": 130500, "6030": 144500, "6040": 310000, "6050": 122500,
        "6060": 126000, "6070": 165000, "6080": 3500, "6090": 31000, "6100": 91500,
    },
}
EXPECTED_PNL_TOTALS_BY_PERIOD = {
    (4, 4): {"revenue": 9817500, "cogs": 3132500, "gross": 6685000, "opex": 4486000, "net": 2199000},
    (5, 5): {"revenue": 10657500, "cogs": 3205000, "gross": 7452500, "opex": 4624000, "net": 2828500},
    (6, 6): {"revenue": 9552500, "cogs": 3047500, "gross": 6505000, "opex": 4714500, "net": 1790500},
    (4, 6): {"revenue": 30027500, "cogs": 9385000, "gross": 20642500, "opex": 13824500, "net": 6818000},
}

BRIGHTFIX_MAPPING = IngestionMapping(
    columns=ColumnMapping(
        transaction_id="Bank Transaction ID",
        transaction_date="Transaction Date",
        posted_date="Posted Date",
        description="Description",
        amount="Amount (USD)",
        currency="Currency",
        bank_account="Bank Account",
    ),
    sheet_name="Raw Bank Transactions",
    header_row=4,
    source_file_column="Source File",
)


def dataset_bytes() -> bytes:
    """Load the original workbook without modifying it."""
    return DATASET_PATH.read_bytes()


def source_sha256() -> str:
    """Provide an integrity check for tests that use the source workbook."""
    return sha256(dataset_bytes()).hexdigest()
