from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.main import create_app
from app.repositories.memory import InMemoryUnitOfWork


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "mongodb_uri": SecretStr("mongodb://example.com:27017"),
        "mongodb_database": "finz_test",
        "repository_backend": "mongo",
        "qbo_client_id": SecretStr("client"),
        "qbo_client_secret": SecretStr("secret"),
        "qbo_redirect_uri": "https://demo.example.com/api/v1/integrations/qbo/callback",
        "qbo_environment": "sandbox",
        "qbo_authorization_url": "https://appcenter.intuit.com/connect/oauth2",
        "qbo_token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "qbo_base_url": "https://sandbox-quickbooks.api.intuit.com/v3",
        "qbo_scope": "com.intuit.quickbooks.accounting",
        "app_environment": "development",
        "public_base_url": "https://demo.example.com",
        "frontend_static_dir": None,
        "demo_reset_secret": SecretStr("Finz-Reset-7zN4pQ8vK2mR6xC9sL3wT5yH"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("overrides", "missing_name"),
    [
        ({"repository_backend": "memory"}, "FINZ_REPOSITORY_BACKEND"),
        ({"mongodb_uri": SecretStr("mongodb://placeholder")}, "MONGODB_URI"),
        ({"qbo_environment": "production"}, "QBO_ENVIRONMENT"),
        ({"qbo_client_id": None}, "QBO_CLIENT_ID"),
        ({"qbo_client_secret": None}, "QBO_CLIENT_SECRET"),
        ({"qbo_redirect_uri": None}, "QBO_REDIRECT_URI"),
        ({"public_base_url": "http://demo.example.com"}, "APP_BASE_URL"),
        ({"demo_reset_secret": None}, "FINZ_DEMO_RESET_SECRET"),
        (
            {"demo_reset_secret": SecretStr("<dedicated-random-reset-secret>")},
            "FINZ_DEMO_RESET_SECRET",
        ),
        (
            {"demo_reset_secret": SecretStr("short-reset-secret")},
            "FINZ_DEMO_RESET_SECRET",
        ),
        (
            {"demo_reset_secret": SecretStr("a" * 40)},
            "FINZ_DEMO_RESET_SECRET",
        ),
    ],
)
def test_production_rejects_unsafe_runtime_configuration(
    overrides: dict[str, object], missing_name: str
) -> None:
    """Removing a required production boundary must prevent app creation."""
    settings = _settings(app_environment="production", **overrides)

    with pytest.raises(ConfigurationError) as error:
        create_app(settings=settings, unit_of_work=InMemoryUnitOfWork())

    assert error.value.missing_names == (missing_name,)


STATIC_BUILD = Path(__file__).parent / "fixtures" / "frontend-build"
PROJECT_ROOT = Path(__file__).parents[3]


@pytest.mark.parametrize(
    ("overrides", "missing_name"),
    [
        (
            {"qbo_base_url": "https://quickbooks.api.intuit.com/v3"},
            "QBO_BASE_URL",
        ),
        (
            {"qbo_authorization_url": "https://example.com/connect/oauth2"},
            "QBO_AUTHORIZATION_URL",
        ),
        (
            {"qbo_token_url": "https://example.com/oauth2/v1/tokens/bearer"},
            "QBO_TOKEN_URL",
        ),
        ({"qbo_scope": "openid"}, "QBO_SCOPE"),
        (
            {"qbo_redirect_uri": "https://other.example.com/api/v1/integrations/qbo/callback"},
            "QBO_REDIRECT_URI",
        ),
    ],
)
def test_production_rejects_non_sandbox_or_untrusted_qbo_endpoints(
    overrides: dict[str, object], missing_name: str
) -> None:
    settings = _settings(
        app_environment="production",
        frontend_static_dir=STATIC_BUILD,
        **overrides,
    )

    with pytest.raises(ConfigurationError) as error:
        create_app(settings=settings, unit_of_work=InMemoryUnitOfWork())

    assert error.value.missing_names == (missing_name,)


def test_render_blueprint_uses_free_plan_and_mongo_repository() -> None:
    """The checked-in MVP blueprint must be free-tier and production-safe by default."""
    blueprint = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "plan: free" in blueprint
    assert "key: FINZ_REPOSITORY_BACKEND\n        value: mongo" in blueprint


def test_production_startup_fails_when_mongo_index_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableMongo:
        closed = False

        async def create_indexes(self) -> None:
            raise RuntimeError("mongodb://user:secret@host failed")

        async def aclose(self) -> None:
            self.closed = True

    unavailable = UnavailableMongo()
    monkeypatch.setattr(
        "app.main.MongoUnitOfWork.from_uri",
        lambda *_args, **_kwargs: unavailable,
    )
    app = create_app(
        settings=_settings(
            app_environment="production",
            frontend_static_dir=STATIC_BUILD,
        )
    )

    with pytest.raises(
        RuntimeError, match="repository initialization failed"
    ) as error:
        with TestClient(app):
            pass

    assert error.value.__cause__ is None
    assert "secret" not in repr(error.value)
    assert unavailable.closed is True


def test_production_startup_requires_transaction_capable_mongo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StandaloneMongo:
        closed = False

        async def create_indexes(self) -> None:
            return None

        async def supports_transactions(self) -> bool:
            return False

        async def aclose(self) -> None:
            self.closed = True

    standalone = StandaloneMongo()
    monkeypatch.setattr(
        "app.main.MongoUnitOfWork.from_uri",
        lambda *_args, **_kwargs: standalone,
    )
    app = create_app(
        settings=_settings(
            app_environment="production",
            frontend_static_dir=STATIC_BUILD,
        )
    )

    with pytest.raises(RuntimeError, match="transaction-capable") as error:
        with TestClient(app):
            pass

    assert error.value.__cause__ is None
    assert standalone.closed is True


def test_development_serves_static_assets_and_spa_deep_links() -> None:
    """Removing static hosting or SPA fallback would break direct browser navigation."""
    app = create_app(
        settings=_settings(frontend_static_dir=STATIC_BUILD),
        unit_of_work=InMemoryUnitOfWork(),
    )

    with TestClient(app) as client:
        assert client.get("/assets/app.js").text == "window.finz = true;\n"
        assert client.get("/review").text == "<main>Finz demo</main>\n"


def test_spa_fallback_never_shadows_api_health_or_docs() -> None:
    """Broad static fallback must not turn reserved backend routes into HTML."""
    app = create_app(
        settings=_settings(frontend_static_dir=STATIC_BUILD),
        unit_of_work=InMemoryUnitOfWork(),
    )

    with TestClient(app) as client:
        assert client.get("/api/not-a-route").status_code == 404
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/docs").status_code == 200


def test_ready_returns_sanitized_503_when_repository_ping_fails() -> None:
    """A repository outage must fail readiness without exposing its exception."""

    class UnavailableUnitOfWork(InMemoryUnitOfWork):
        async def ping(self) -> bool:
            raise RuntimeError("mongodb://user:secret@host failed")

    app = create_app(settings=_settings(), unit_of_work=UnavailableUnitOfWork())

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Required repository is unavailable"}
    assert "secret" not in response.text


def test_production_requires_existing_frontend_build() -> None:
    """A production deploy without built frontend files must fail before serving traffic."""
    settings = _settings(
        app_environment="production",
        repository_backend="mongo",
        mongodb_uri=SecretStr("mongodb://example.com:27017"),
        qbo_client_id=SecretStr("client"),
        qbo_client_secret=SecretStr("secret"),
        qbo_redirect_uri="https://demo.example.com/api/v1/integrations/qbo/callback",
        public_base_url="https://demo.example.com",
        frontend_static_dir=STATIC_BUILD / "missing-dist",
    )

    with pytest.raises(RuntimeError, match="frontend directory"):
        create_app(settings=settings, unit_of_work=InMemoryUnitOfWork())
