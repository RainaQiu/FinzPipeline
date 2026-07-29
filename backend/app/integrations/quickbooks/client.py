from typing import Any

import httpx

from app.config import Settings


class QuickBooksIntegrationError(Exception):
    def __init__(
        self,
        stage: str,
        upstream_status: int,
        upstream_error: str,
    ) -> None:
        super().__init__(f"{stage}: {upstream_error}")
        self.stage = stage
        self.upstream_status = upstream_status
        self.upstream_error = upstream_error


def _safe_upstream_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "non_json_response"
    if not isinstance(payload, dict):
        return "unexpected_response"
    return str(
        payload.get("error")
        or payload.get("Fault", {}).get("Error", [{}])[0].get("Message")
        or "unknown_upstream_error"
    )


class QuickBooksClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: dict[str, Any] | None = None

    async def complete_authorization(
        self,
        code: str,
        realm_id: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                self._settings.qbo_token_url,
                auth=(
                    self._settings.qbo_client_id,
                    self._settings.qbo_client_secret,
                ),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._settings.qbo_redirect_uri,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if token_response.is_error:
                raise QuickBooksIntegrationError(
                    stage="token_exchange",
                    upstream_status=token_response.status_code,
                    upstream_error=_safe_upstream_error(token_response),
                )
            tokens = token_response.json()

            company_response = await client.get(
                (
                    f"{self._settings.qbo_base_url}/company/{realm_id}"
                    f"/companyinfo/{realm_id}"
                ),
                params={"minorversion": "75"},
                headers={
                    "Authorization": f"Bearer {tokens['access_token']}",
                    "Accept": "application/json",
                },
            )
            if company_response.is_error:
                raise QuickBooksIntegrationError(
                    stage="company_info",
                    upstream_status=company_response.status_code,
                    upstream_error=_safe_upstream_error(company_response),
                )
            company_info = company_response.json()["CompanyInfo"]

        # In-memory only for the first OAuth milestone. MongoDB persistence
        # and encryption are added in the next integration milestone.
        self._connection = {
            "realm_id": realm_id,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": tokens.get("expires_in"),
            "refresh_token_expires_in": tokens.get("x_refresh_token_expires_in"),
            "company_name": company_info["CompanyName"],
        }
        return {
            "connected": True,
            "company_name": company_info["CompanyName"],
            "realm_id": realm_id,
            "environment": self._settings.qbo_environment,
        }
