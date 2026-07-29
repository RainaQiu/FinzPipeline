from dataclasses import dataclass
import os

from pydantic import SecretStr

from app.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class Settings:
    """Typed settings read only when explicitly requested."""

    mongodb_uri: SecretStr
    mongodb_database: str
    repository_backend: str
    qbo_client_id: SecretStr | None
    qbo_client_secret: SecretStr | None
    qbo_redirect_uri: str | None
    qbo_environment: str
    qbo_authorization_url: str
    qbo_token_url: str
    qbo_base_url: str
    qbo_scope: str

    @classmethod
    def from_environment(cls, require_qbo: bool = False) -> "Settings":
        qbo_values = {
            "QBO_CLIENT_ID": os.getenv("QBO_CLIENT_ID", "").strip(),
            "QBO_CLIENT_SECRET": os.getenv("QBO_CLIENT_SECRET", "").strip(),
            "QBO_REDIRECT_URI": os.getenv("QBO_REDIRECT_URI", "").strip(),
        }
        missing_names = tuple(name for name, value in qbo_values.items() if not value)
        if require_qbo and missing_names:
            raise ConfigurationError(missing_names)

        repository_backend = os.getenv("FINZ_REPOSITORY_BACKEND", "memory").strip().lower()
        if repository_backend not in {"memory", "mongo"}:
            raise ValueError("FINZ_REPOSITORY_BACKEND must be memory or mongo")

        return cls(
            mongodb_uri=SecretStr(
                os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017").strip()
            ),
            mongodb_database=os.getenv("MONGODB_DATABASE", "finz_ledger_bridge").strip()
            or "finz_ledger_bridge",
            repository_backend=repository_backend,
            qbo_client_id=SecretStr(qbo_values["QBO_CLIENT_ID"])
            if qbo_values["QBO_CLIENT_ID"]
            else None,
            qbo_client_secret=SecretStr(qbo_values["QBO_CLIENT_SECRET"])
            if qbo_values["QBO_CLIENT_SECRET"]
            else None,
            qbo_redirect_uri=qbo_values["QBO_REDIRECT_URI"] or None,
            qbo_environment=os.getenv("QBO_ENVIRONMENT", "sandbox").strip() or "sandbox",
            qbo_authorization_url=os.getenv(
                "QBO_AUTHORIZATION_URL", "https://appcenter.intuit.com/connect/oauth2"
            ).strip(),
            qbo_token_url=os.getenv(
                "QBO_TOKEN_URL", "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
            ).strip(),
            qbo_base_url=os.getenv(
                "QBO_BASE_URL", "https://sandbox-quickbooks.api.intuit.com/v3"
            ).strip(),
            qbo_scope=os.getenv(
                "QBO_SCOPE", "com.intuit.quickbooks.accounting"
            ).strip(),
        )
