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
    monkeypatch.setenv("FINZ_DEMO_ACCESS_CODE", "private-interviewer-code")

    settings = Settings.from_environment(require_qbo=True)

    assert "private-password" not in str(settings.mongodb_uri)
    assert "private-client-secret" not in str(settings.qbo_client_secret)
    assert "private-interviewer-code" not in repr(settings)


def test_gemini_settings_are_optional_and_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GEMINI_ENABLED", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MAX_CANDIDATES_PER_UPLOAD", raising=False)

    settings = Settings.from_environment()

    assert settings.gemini_enabled is False
    assert settings.gemini_api_key is None
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_max_candidates_per_upload == 10


@pytest.mark.parametrize("value", ["1", "yes", "on", "TRUE ", "enabled"])
def test_gemini_enabled_accepts_only_strict_boolean_text(monkeypatch, value):
    monkeypatch.setenv("GEMINI_ENABLED", value)

    with pytest.raises(ValueError, match="GEMINI_ENABLED"):
        Settings.from_environment()


@pytest.mark.parametrize("value", ["-1", "11", "not-an-integer"])
def test_gemini_candidate_cap_is_bounded(monkeypatch, value):
    monkeypatch.setenv("GEMINI_MAX_CANDIDATES_PER_UPLOAD", value)

    with pytest.raises(ValueError, match="GEMINI_MAX_CANDIDATES_PER_UPLOAD"):
        Settings.from_environment()


def test_gemini_key_is_redacted_from_settings_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-gemini-key")

    settings = Settings.from_environment()

    assert "private-gemini-key" not in repr(settings)
