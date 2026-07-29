from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Mapping


class Direction(StrEnum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


def _require_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer number of cents")


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class RawRecord:
    id: str
    source_filename: str
    source_file_sha256: str
    source_sheet: str
    source_row_number: int
    raw_values: Mapping[str, object]
    raw_row_sha256: str
    ingested_at: datetime

    def __post_init__(self) -> None:
        _require_int(self.source_row_number, "source_row_number")
        object.__setattr__(
            self,
            "raw_values",
            MappingProxyType(
                {key: _freeze_value(value) for key, value in self.raw_values.items()}
            ),
        )


@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    id: str
    raw_record_id: str
    bank_transaction_id: str
    transaction_date: date
    posted_date: date
    description_original: str
    description_normalized: str
    amount_minor: int
    currency: Literal["USD"]
    direction: Direction
    bank_account_number: Literal["1000", "1010"]

    def __post_init__(self) -> None:
        _require_int(self.amount_minor, "amount_minor")
        if self.currency != "USD":
            raise ValueError("currency must be USD")
        if self.bank_account_number not in {"1000", "1010"}:
            raise ValueError("bank_account_number must be 1000 or 1010")
