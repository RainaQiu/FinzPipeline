from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

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
    app_environment: str
    public_base_url: str
    frontend_static_dir: Path | None
    demo_reset_secret: SecretStr | None

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
                os.getenv("MONGODB_URI", "").strip()
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
            app_environment=os.getenv("APP_ENVIRONMENT", "development").strip().lower()
            or "development",
            public_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000").strip(),
            frontend_static_dir=(
                Path(value).expanduser()
                if (value := os.getenv("FRONTEND_STATIC_DIR", "").strip())
                else None
            ),
            demo_reset_secret=(
                SecretStr(value)
                if (value := os.getenv("FINZ_DEMO_RESET_SECRET", "").strip())
                else None
            ),
        )

    def validate_public_runtime(self) -> None:
        """Reject unsafe public deployment settings without exposing their values."""
        if self.app_environment != "production":
            return
        if self.repository_backend != "mongo":
            raise ConfigurationError(("FINZ_REPOSITORY_BACKEND",))
        mongodb_uri = self.mongodb_uri.get_secret_value().strip().lower()
        if not mongodb_uri or "placeholder" in mongodb_uri or "<" in mongodb_uri:
            raise ConfigurationError(("MONGODB_URI",))
        if self.qbo_environment.lower() != "sandbox":
            raise ConfigurationError(("QBO_ENVIRONMENT",))
        if self.qbo_client_id is None:
            raise ConfigurationError(("QBO_CLIENT_ID",))
        if self.qbo_client_secret is None:
            raise ConfigurationError(("QBO_CLIENT_SECRET",))
        if not self.qbo_redirect_uri:
            raise ConfigurationError(("QBO_REDIRECT_URI",))
        if self.qbo_authorization_url.rstrip("/") != (
            "https://appcenter.intuit.com/connect/oauth2"
        ):
            raise ConfigurationError(("QBO_AUTHORIZATION_URL",))
        if self.qbo_token_url.rstrip("/") != (
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        ):
            raise ConfigurationError(("QBO_TOKEN_URL",))
        if self.qbo_base_url.rstrip("/") != (
            "https://sandbox-quickbooks.api.intuit.com/v3"
        ):
            raise ConfigurationError(("QBO_BASE_URL",))
        if self.qbo_scope != "com.intuit.quickbooks.accounting":
            raise ConfigurationError(("QBO_SCOPE",))
        reset_secret = (
            self.demo_reset_secret.get_secret_value().strip().lower()
            if self.demo_reset_secret is not None
            else ""
        )
        if not reset_secret or "placeholder" in reset_secret or "<" in reset_secret:
            raise ConfigurationError(("FINZ_DEMO_RESET_SECRET",))
        if urlparse(self.public_base_url).scheme != "https":
            raise ConfigurationError(("APP_BASE_URL",))
        expected_redirect = (
            self.public_base_url.rstrip("/")
            + "/api/v1/integrations/qbo/callback"
        )
        if self.qbo_redirect_uri != expected_redirect:
            raise ConfigurationError(("QBO_REDIRECT_URI",))
        if self.frontend_static_dir is None or not (self.frontend_static_dir / "index.html").is_file():
            raise RuntimeError("Production startup requires a built frontend directory with index.html")
