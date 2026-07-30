from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from app.repositories.memory import InMemoryUnitOfWork


PROJECT_ROOT = Path(__file__).parents[3]


def _settings(secret: SecretStr | None = SecretStr("dedicated-reset-secret")) -> Settings:
    return Settings(
        mongodb_uri=SecretStr(""),
        mongodb_database="finz_test",
        repository_backend="memory",
        qbo_client_id=None,
        qbo_client_secret=None,
        qbo_redirect_uri=None,
        qbo_environment="sandbox",
        qbo_authorization_url="https://appcenter.intuit.com/connect/oauth2",
        qbo_token_url="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        qbo_base_url="https://sandbox-quickbooks.api.intuit.com/v3",
        qbo_scope="com.intuit.quickbooks.accounting",
        app_environment="development",
        public_base_url="http://localhost:8000",
        frontend_static_dir=None,
        demo_reset_secret=secret,
        demo_access_code=SecretStr("Finz-Interview-9vK2mR6x"),
    )


def test_reset_endpoint_requires_dedicated_secret_and_returns_redacted_status(
    monkeypatch,
) -> None:
    app = create_app(settings=_settings(), unit_of_work=InMemoryUnitOfWork())
    compared: list[tuple[str, str]] = []

    def observed_compare(presented: str, expected: str) -> bool:
        compared.append((presented, expected))
        return presented == expected

    monkeypatch.setattr("app.api.demo_reset.compare_digest", observed_compare)

    with TestClient(app) as client:
        missing = client.post("/api/v1/admin/reset")
        wrong = client.post(
            "/api/v1/admin/reset",
            headers={"X-Finz-Reset-Secret": "wrong"},
        )
        accepted = client.post(
            "/api/v1/admin/reset",
            headers={"X-Finz-Reset-Secret": "dedicated-reset-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "Reset authorization failed"}
    assert "wrong" not in wrong.text
    assert compared == [
        ("", "dedicated-reset-secret"),
        ("wrong", "dedicated-reset-secret"),
        ("dedicated-reset-secret", "dedicated-reset-secret"),
    ]
    assert accepted.status_code == 200
    assert accepted.json() == {
        "status": "reset_complete",
        "scope": "shared_demo_workspace",
        "qbo_connection": "preserved",
    }


def test_reset_endpoint_redacts_repository_failure() -> None:
    uow = InMemoryUnitOfWork()

    class FailingResetRepository:
        async def clear_shared_workspace(
            self, *, lease_id, clock, lease_duration
        ) -> None:
            raise RuntimeError("mongodb://user:secret@example/reset failed")

        async def add(self, run):
            return run

    uow.demo_reset = FailingResetRepository()
    app = create_app(settings=_settings(), unit_of_work=uow)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/admin/reset",
            headers={"X-Finz-Reset-Secret": "dedicated-reset-secret"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Shared workspace reset failed"}
    assert "secret" not in response.text


def test_weekly_reset_workflow_uses_only_secret_reference_and_bounded_curl() -> None:
    workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "weekly-demo-reset.yml"
    ).read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "secrets.FINZ_DEMO_RESET_SECRET" in workflow
    assert "vars.FINZ_DEMO_BASE_URL" in workflow
    assert "--max-time 30" in workflow
    assert "--retry 2" in workflow
    assert "=~ ^https://[^/[:space:]]+" in workflow
    assert "dedicated-reset-secret" not in workflow
