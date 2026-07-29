import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError


def test_settings_do_not_require_qbo_for_core(monkeypatch):
    """Removing QBO configuration must not prevent non-QBO work from starting."""
    for name in ("QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_environment(require_qbo=False)

    assert settings.mongodb_database == "finz_ledger_bridge"
    assert settings.repository_backend == "memory"
    assert settings.qbo_client_id is None


def test_qbo_settings_report_only_missing_variable_names(monkeypatch):
    """A missing QBO variable is actionable without exposing any supplied secret."""
    monkeypatch.setenv("QBO_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("QBO_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.delenv("QBO_CLIENT_ID", raising=False)

    with pytest.raises(ConfigurationError) as error:
        Settings.from_environment(require_qbo=True)

    assert error.value.missing_names == ("QBO_CLIENT_ID",)
    assert "test-secret" not in str(error.value)


def test_secret_settings_redact_string_representation(monkeypatch):
    """Accidentally formatting settings must not reveal database or QBO secrets."""
    monkeypatch.setenv("MONGODB_URI", "mongodb://user:private-password@localhost:27017")
    monkeypatch.setenv("QBO_CLIENT_ID", "private-client-id")
    monkeypatch.setenv("QBO_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("QBO_REDIRECT_URI", "http://localhost/callback")

    settings = Settings.from_environment(require_qbo=True)

    assert "private-password" not in str(settings.mongodb_uri)
    assert "private-client-secret" not in str(settings.qbo_client_secret)
