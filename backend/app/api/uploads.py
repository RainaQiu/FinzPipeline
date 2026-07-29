"""Upload and ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_ledger_bridge
from app.services.ingestion import IngestionMapping, MAX_FILE_BYTES
from app.services.ledger_bridge import InvalidUploadError, LedgerBridgeService
from app.services.normalization import ColumnMapping


router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])
UPLOAD_READ_CHUNK_BYTES = 64 * 1024


class MappingColumns(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1)
    transaction_date: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    bank_account: str = Field(min_length=1)
    posted_date: str | None = None


class ProcessUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: MappingColumns
    sheet_name: str | None = None
    header_row: int = Field(default=1, ge=1)
    source_file_column: str | None = None

    def to_domain(self) -> IngestionMapping:
        return IngestionMapping(
            columns=ColumnMapping(**self.columns.model_dump()),
            sheet_name=self.sheet_name,
            header_row=self.header_row,
            source_file_column=self.source_file_column,
        )


async def _bounded_upload_data(upload: UploadFile) -> bytes:
    if upload.size is not None and upload.size > MAX_FILE_BYTES:
        raise InvalidUploadError(
            "The uploaded file exceeds the size limit.",
            details={"max_bytes": MAX_FILE_BYTES},
        )
    data = bytearray()
    while chunk := await upload.read(UPLOAD_READ_CHUNK_BYTES):
        data.extend(chunk)
        if len(data) > MAX_FILE_BYTES:
            raise InvalidUploadError(
                "The uploaded file exceeds the size limit.",
                details={"max_bytes": MAX_FILE_BYTES},
            )
    return bytes(data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_upload(
    file: UploadFile = File(...),
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    try:
        if not file.filename:
            raise InvalidUploadError("The file field must include a filename.")
        data = await _bounded_upload_data(file)
        return await service.create_upload(
            filename=file.filename,
            media_type=file.content_type or "application/octet-stream",
            data=data,
        )
    finally:
        await file.close()


@router.get("/{upload_id}")
async def get_upload(
    upload_id: str,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.get_upload(upload_id)


@router.post("/{upload_id}/process")
async def process_upload(
    upload_id: str,
    request: ProcessUploadRequest,
    service: LedgerBridgeService = Depends(get_ledger_bridge),
) -> dict[str, object]:
    return await service.process_upload(upload_id, request.to_domain())
