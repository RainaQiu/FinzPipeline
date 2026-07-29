"""Safe and stable API error envelopes."""

from io import BytesIO

from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request
from starlette.datastructures import UploadFile

from app.api.uploads import UPLOAD_READ_CHUNK_BYTES, _bounded_upload_data
from app.main import create_app
from app.services.ingestion import MAX_FILE_BYTES
from app.services.ledger_bridge import InvalidUploadError


def test_unknown_upload_uses_safe_correlated_404() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/uploads/missing",
        headers={"x-correlation-id": "request-123"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Upload not found.",
            "retryable": False,
            "correlation_id": "request-123",
            "details": {},
        }
    }
    assert "traceback" not in response.text.lower()


def test_upload_rejects_unsupported_media_type_without_echoing_bytes() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/uploads",
        files={"file": ("secret.exe", b"super-secret-token", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_upload"
    assert "super-secret-token" not in response.text


def test_upload_rejects_extension_media_type_mismatch() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/uploads",
        files={
            "file": (
                "not-a-workbook.exe",
                b"PK",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_upload"


def test_upload_route_does_not_buffer_the_entire_request_body(monkeypatch) -> None:
    """Reintroducing request.body() would restore the pre-limit memory spike."""

    async def fail_if_body_is_buffered(self: Request) -> bytes:
        raise AssertionError("upload route must stream the multipart file")

    monkeypatch.setattr(Request, "body", fail_if_body_is_buffered)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/uploads",
        files={"file": ("bank.csv", b"id,amount\n1,10.00\n", "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["size_bytes"] == 18


@pytest.mark.asyncio
async def test_upload_with_unknown_declared_size_stops_after_crossing_the_limit() -> None:
    """Missing multipart size metadata must not bypass bounded chunk reads."""
    source = BytesIO(b"x" * (MAX_FILE_BYTES + UPLOAD_READ_CHUNK_BYTES * 2))
    upload = UploadFile(file=source, filename="too-large.csv", size=None)

    with pytest.raises(InvalidUploadError, match="size limit"):
        await _bounded_upload_data(upload)

    assert source.tell() <= MAX_FILE_BYTES + UPLOAD_READ_CHUNK_BYTES


def test_malformed_mapping_uses_validation_error_envelope() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/uploads/missing/process",
        json={"header_row": 0, "columns": {}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["correlation_id"]


def test_wrong_qbo_report_scope_uses_safe_reconciliation_error() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/reconciliations",
        json={
            "start_date": "2026-04-01",
            "end_date": "2026-06-30",
            "qbo_report": {
                "Header": {
                    "ReportBasis": "Accrual",
                    "StartPeriod": "2026-04-01",
                    "EndPeriod": "2026-06-30",
                    "Currency": "USD",
                },
                "Rows": {"Row": []},
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_reconciliation"
    assert "traceback" not in response.text.lower()
