from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.main import _QboRuntimeSettings
from app.integrations.quickbooks.client import QuickBooksIntegrationError
from app.repositories.memory import InMemoryUnitOfWork


class FakeQboClient:
    async def complete_authorization(self, code, realm_id):
        assert code == "temporary-code"
        assert realm_id == "9341457609469713"
        return {
            "connected": True,
            "company_name": "BrightFix Home Services LLC",
            "realm_id": realm_id,
            "environment": "sandbox",
        }


class FailingQboClient:
    async def complete_authorization(self, code, realm_id):
        raise QuickBooksIntegrationError(
            stage="token_exchange",
            upstream_status=400,
            upstream_error="invalid_client",
        )


class UnexpectedFailingQboClient:
    async def complete_authorization(self, code, realm_id):
        raise KeyError("CompanyInfo")


@pytest.fixture(autouse=True)
def qbo_test_environment(monkeypatch):
    monkeypatch.setenv("QBO_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("QBO_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "QBO_REDIRECT_URI",
        "http://localhost:8000/api/v1/integrations/qbo/callback",
    )
    monkeypatch.setenv("QBO_ENVIRONMENT", "sandbox")


def test_health_reports_service_ready():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "finz-ledger-bridge",
        "environment": "sandbox",
    }


def test_qbo_runtime_settings_repr_redacts_client_credentials():
    """Logging runtime settings must not leak the OAuth client credentials."""
    settings = _QboRuntimeSettings(
        qbo_client_id="test-client-id",
        qbo_client_secret="test-client-secret",
        qbo_redirect_uri="http://localhost/callback",
        qbo_environment="sandbox",
        qbo_authorization_url="https://example.test/authorize",
        qbo_token_url="https://example.test/token",
        qbo_base_url="https://example.test/api",
        qbo_scope="scope",
    )

    representation = repr(settings)

    assert "test-client-id" not in representation
    assert "test-client-secret" not in representation


def test_qbo_connect_redirects_to_intuit_with_required_oauth_parameters():
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/integrations/qbo/connect",
        follow_redirects=False,
    )

    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://appcenter.intuit.com/connect/oauth2"
    )
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == [
        "http://localhost:8000/api/v1/integrations/qbo/callback"
    ]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["com.intuit.quickbooks.accounting"]
    assert len(query["state"][0]) >= 32
    cookie = response.headers["set-cookie"]
    assert "finz_qbo_oauth_state=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_qbo_callback_rejects_unknown_state():
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/integrations/qbo/callback",
        params={"code": "temporary-code", "state": "forged", "realmId": "123"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired OAuth state"}


def test_qbo_callback_exchanges_code_and_verifies_company():
    client = TestClient(create_app(qbo_client=FakeQboClient()))
    connect_response = client.get(
        "/api/v1/integrations/qbo/connect",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(connect_response.headers["location"]).query)["state"][0]

    response = client.get(
        "/api/v1/integrations/qbo/callback",
        params={
            "code": "temporary-code",
            "state": state,
            "realmId": "9341457609469713",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "company_name": "BrightFix Home Services LLC",
        "realm_id": "9341457609469713",
        "environment": "sandbox",
    }


def test_qbo_state_survives_app_instance_when_repository_is_shared():
    shared_uow = InMemoryUnitOfWork()
    first_client = TestClient(create_app(unit_of_work=shared_uow))
    connect_response = first_client.get(
        "/api/v1/integrations/qbo/connect", follow_redirects=False
    )
    state = parse_qs(urlparse(connect_response.headers["location"]).query)["state"][0]
    cookie = first_client.cookies.get("finz_qbo_oauth_state")

    second_client = TestClient(
        create_app(qbo_client=FakeQboClient(), unit_of_work=shared_uow)
    )
    second_client.cookies.set("finz_qbo_oauth_state", cookie)
    response = second_client.get(
        "/api/v1/integrations/qbo/callback",
        params={
            "code": "temporary-code",
            "state": state,
            "realmId": "9341457609469713",
        },
    )

    assert response.status_code == 200


def test_qbo_callback_reports_safe_upstream_failure_stage_without_upstream_details():
    client = TestClient(create_app(qbo_client=FailingQboClient()))
    connect_response = client.get(
        "/api/v1/integrations/qbo/connect",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(connect_response.headers["location"]).query)["state"][0]

    response = client.get(
        "/api/v1/integrations/qbo/callback",
        params={"code": "temporary-code", "state": state, "realmId": "123"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "message": "QuickBooks integration failed",
            "stage": "token_exchange",
            "upstream_status": 400,
        }
    }


def test_qbo_callback_redacts_unexpected_exception_type():
    client = TestClient(create_app(qbo_client=UnexpectedFailingQboClient()))
    connect_response = client.get(
        "/api/v1/integrations/qbo/connect",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(connect_response.headers["location"]).query)["state"][0]

    response = client.get(
        "/api/v1/integrations/qbo/callback",
        params={"code": "temporary-code", "state": state, "realmId": "123"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "message": "QuickBooks authorization or company verification failed",
            "stage": "unexpected",
        }
    }
