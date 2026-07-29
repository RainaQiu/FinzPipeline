from datetime import datetime, timezone

from app.domain.demo import DemoGrant, QboConnection


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
