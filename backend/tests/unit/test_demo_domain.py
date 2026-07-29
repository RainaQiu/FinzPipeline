from datetime import datetime, timedelta, timezone

import pytest

from app.domain.demo import (
    DemoGrant,
    ExecutionLease,
    PipelineContext,
    QboConnection,
    ReconciliationRunRecord,
    ResetRun,
    SyncRunRecord,
    UploadRecord,
)


def test_demo_grant_never_retains_plaintext_token():
    """Persisting a grant must never make its bearer token recoverable."""
    grant = DemoGrant(
        token_hash="a" * 64,
        expires_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert not hasattr(grant, "token")


def test_qbo_connection_repr_redacts_ciphertext():
    """Logs must not reveal stored QBO credentials."""
    connection = QboConnection(
        realm_id="realm-1",
        company_name="BrightFix Home Services LLC",
        encrypted_access_token="cipher-a",
        encrypted_refresh_token="cipher-r",
        access_expires_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        refresh_expires_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert "cipher-a" not in repr(connection)
    assert "cipher-r" not in repr(connection)


def test_upload_record_freezes_caller_owned_error_summary():
    """Later caller mutations must not change a persisted upload's errors."""
    errors = ["first"]
    record = UploadRecord(
        id="upload-1",
        original_filename="source.csv",
        media_type="text/csv",
        sha256="a" * 64,
        data=b"source",
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        error_summary=errors,
    )

    errors.append("mutated")

    assert record.error_summary == ("first",)


def test_upload_record_rejects_non_string_error_summary_items():
    """Error summaries are persisted display strings, never arbitrary values."""
    with pytest.raises(TypeError):
        UploadRecord(
            id="upload-1",
            original_filename="source.csv",
            media_type="text/csv",
            sha256="a" * 64,
            data=b"source",
            created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
            error_summary=("first", 2),
        )


def test_demo_records_canonicalize_all_datetimes_to_utc_milliseconds():
    source = datetime(
        2026,
        7,
        30,
        12,
        34,
        56,
        123456,
        tzinfo=timezone(timedelta(hours=8)),
    )
    later = source + timedelta(hours=1)
    canonical_source = datetime(
        2026, 7, 30, 4, 34, 56, 123000, tzinfo=timezone.utc
    )
    canonical_later = datetime(
        2026, 7, 30, 5, 34, 56, 123000, tzinfo=timezone.utc
    )
    records_and_fields = (
        (
            UploadRecord(
                id="finz-test-upload-time",
                original_filename="finz-test.csv",
                media_type="text/csv",
                sha256="a" * 64,
                data=b"source",
                created_at=source,
                completed_at=later,
            ),
            (
                ("created_at", canonical_source),
                ("completed_at", canonical_later),
            ),
        ),
        (
            PipelineContext(
                id="finz-test-context-time",
                upload_id="finz-test-upload-time",
                status="ready",
                transaction_statuses={},
                transfer_pairs={},
                created_at=source,
                updated_at=later,
            ),
            (("created_at", canonical_source), ("updated_at", canonical_later)),
        ),
        (
            SyncRunRecord(
                id="finz-test-sync-time",
                status="complete",
                item_views={},
                started_at=source,
                completed_at=later,
            ),
            (
                ("started_at", canonical_source),
                ("completed_at", canonical_later),
            ),
        ),
        (
            ReconciliationRunRecord(
                id="finz-test-reconciliation-time",
                status="complete",
                account_views={},
                created_at=source,
            ),
            (("created_at", canonical_source),),
        ),
        (
            DemoGrant(
                token_hash="finz-test-grant-time",
                expires_at=later,
                created_at=source,
            ),
            (("expires_at", canonical_later), ("created_at", canonical_source)),
        ),
        (
            QboConnection(
                realm_id="finz-test-realm-time",
                company_name="Finz Test Company",
                encrypted_access_token="finz-test-access",
                encrypted_refresh_token="finz-test-refresh",
                access_expires_at=later,
                refresh_expires_at=later + timedelta(days=1),
                updated_at=source,
            ),
            (
                ("access_expires_at", canonical_later),
                ("refresh_expires_at", canonical_later + timedelta(days=1)),
                ("updated_at", canonical_source),
            ),
        ),
        (
            ExecutionLease(
                id="finz-test-lease-time",
                acquired_at=source,
                expires_at=later,
            ),
            (("acquired_at", canonical_source), ("expires_at", canonical_later)),
        ),
        (
            ResetRun(
                id="finz-test-reset-time",
                status="complete",
                started_at=source,
                completed_at=later,
            ),
            (
                ("started_at", canonical_source),
                ("completed_at", canonical_later),
            ),
        ),
    )

    for record, field_expectations in records_and_fields:
        for field_name, expected in field_expectations:
            value = getattr(record, field_name)
            assert value == expected
            assert value.tzinfo is timezone.utc
