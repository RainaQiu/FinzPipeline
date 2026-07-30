"""Persistent, encrypted, read-first QuickBooks Sandbox integration."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.domain.accounts import ACCOUNT_DEFINITIONS
from app.domain.demo import QboConnection
from app.integrations.quickbooks.client import QuickBooksIntegrationError
from app.integrations.quickbooks.protocol import QboCreateResult, QboGatewayError
from app.repositories.protocols import AuditEvent


class QboConnectionUnavailable(RuntimeError):
    pass


class QboAccountPreflightError(RuntimeError):
    pass


class PersistentQuickBooksService:
    """Keep QBO tokens encrypted and expose only Sandbox read operations."""

    def __init__(
        self,
        settings: object,
        unit_of_work: object,
        *,
        encryption_key: SecretStr,
        expected_realm_id: str,
        expected_company_name: str = "BrightFix Home Services LLC",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._uow = unit_of_work
        self._cipher = Fernet(encryption_key.get_secret_value().encode("ascii"))
        self._expected_realm_id = expected_realm_id
        self._expected_company_name = expected_company_name
        self._transport = transport
        self._refresh_lock = asyncio.Lock()

    async def complete_authorization(self, code: str, realm_id: str) -> dict[str, Any]:
        if realm_id != self._expected_realm_id:
            raise QboConnectionUnavailable("Unexpected QBO Sandbox company")
        async with self._client() as client:
            tokens = await self._token_request(
                client,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._settings.qbo_redirect_uri,
                },
            )
            company_info = await self._company_info(
                client, realm_id, str(tokens["access_token"])
            )
        company_name = str(company_info.get("CompanyName", ""))
        if company_name != self._expected_company_name:
            raise QboConnectionUnavailable("Unexpected QBO Sandbox company")
        now = datetime.now(timezone.utc)
        connection = self._connection_from_tokens(
            tokens, realm_id=realm_id, company_name=company_name, now=now
        )
        await self._uow.qbo_connection.upsert(connection)
        return {
            "connected": True,
            "company_name": company_name,
            "environment": "sandbox",
        }

    async def status(self) -> dict[str, object]:
        connection = await self._uow.qbo_connection.get()
        audit_events = await self._uow.audit.list()
        write_network_accessed = any(
            event.event_type == "qbo.write_attempted" for event in audit_events
        )
        return {
            "mode": "sandbox_read_only" if connection else "demo_local",
            "connected": connection is not None,
            "company_name": connection.company_name if connection else None,
            "execution_authorized": False,
            "transaction_write_network_accessed": write_network_accessed,
        }

    async def account_preflight(self) -> dict[str, object]:
        connection, access_token = await self._access()
        query = "select * from Account where Active = true maxresults 1000"
        async with self._client() as client:
            response = await client.get(
                f"{self._settings.qbo_base_url}/company/{connection.realm_id}/query",
                params={"query": query, "minorversion": "75"},
                headers=self._bearer(access_token),
            )
        payload = self._checked_json(response, "account_query")
        accounts = payload.get("QueryResponse", {}).get("Account", [])
        mapping: dict[str, str] = {}
        for number, expected in ACCOUNT_DEFINITIONS.items():
            matches = [
                item
                for item in accounts
                if isinstance(item, dict)
                and item.get("Active") is True
                and str(item.get("AcctNum", "")) == number
                and str(item.get("Name", "")) == expected.name
            ]
            if len(matches) != 1:
                raise QboAccountPreflightError(
                    f"QBO account preflight failed for {number}"
                )
            mapping[number] = str(matches[0]["Id"])
        if mapping.get("6060") != "114":
            raise QboAccountPreflightError(
                "6060 Utilities must reuse existing QBO account Id 114"
            )
        return {"status": "ready", "account_count": 21, "mapping": mapping}

    async def profit_and_loss(self, start_date: date, end_date: date) -> dict[str, Any]:
        connection, access_token = await self._access()
        async with self._client() as client:
            response = await client.get(
                (
                    f"{self._settings.qbo_base_url}/company/{connection.realm_id}"
                    "/reports/ProfitAndLoss"
                ),
                params={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "accounting_method": "Cash",
                    "minorversion": "75",
                },
                headers=self._bearer(access_token),
            )
        return self._checked_json(response, "profit_and_loss")

    async def create_entity(
        self,
        kind: str,
        payload: Mapping[str, object],
        *,
        request_id: str,
    ) -> QboCreateResult:
        """Create an already-approved entity; callers own the external write gate."""
        connection, access_token = await self._access()
        preflight = await self.account_preflight()
        mapped = self._map_account_refs(payload, preflight["mapping"])
        await self._uow.audit.append(
            AuditEvent(
                event_type="qbo.write_attempted",
                payload={
                    "realm_id": connection.realm_id,
                    "entity_type": kind,
                    "request_id": request_id,
                },
                occurred_at=datetime.now(timezone.utc),
            )
        )
        async with self._client() as client:
            response = await client.post(
                f"{self._settings.qbo_base_url}/company/{connection.realm_id}/{kind.lower()}",
                params={"minorversion": "75", "requestid": request_id},
                headers=self._bearer(access_token),
                json=mapped,
            )
        if response.is_error:
            raise QboGatewayError(status=response.status_code)
        body = response.json()
        entity = body.get(kind)
        if not isinstance(entity, dict) or not entity.get("Id"):
            raise QboGatewayError(code="invalid_response", retryable=False)
        return QboCreateResult(
            entity_id=str(entity["Id"]),
            sync_token=str(entity.get("SyncToken"))
            if entity.get("SyncToken") is not None
            else None,
        )

    async def _access(self) -> tuple[QboConnection, str]:
        connection = await self._uow.qbo_connection.get()
        if connection is None:
            raise QboConnectionUnavailable("QBO Sandbox is not connected")
        now = datetime.now(timezone.utc)
        if connection.access_expires_at <= now + timedelta(minutes=5):
            async with self._refresh_lock:
                latest = await self._uow.qbo_connection.get()
                if latest is None:
                    raise QboConnectionUnavailable("QBO Sandbox is not connected")
                if latest.access_expires_at <= now + timedelta(minutes=5):
                    latest = await self._refresh(latest, now)
                connection = latest
        return connection, self._decrypt(connection.encrypted_access_token)

    async def _refresh(self, connection: QboConnection, now: datetime) -> QboConnection:
        refresh_token = self._decrypt(connection.encrypted_refresh_token)
        async with self._client() as client:
            tokens = await self._token_request(
                client,
                {"grant_type": "refresh_token", "refresh_token": refresh_token},
            )
        refreshed = self._connection_from_tokens(
            tokens,
            realm_id=connection.realm_id,
            company_name=connection.company_name,
            now=now,
            fallback_refresh_token=refresh_token,
        )
        return await self._uow.qbo_connection.upsert(refreshed)

    def _connection_from_tokens(
        self,
        tokens: dict[str, Any],
        *,
        realm_id: str,
        company_name: str,
        now: datetime,
        fallback_refresh_token: str | None = None,
    ) -> QboConnection:
        refresh_token = str(tokens.get("refresh_token") or fallback_refresh_token or "")
        if not refresh_token or not tokens.get("access_token"):
            raise QboConnectionUnavailable("QBO token response was incomplete")
        return QboConnection(
            realm_id=realm_id,
            company_name=company_name,
            encrypted_access_token=self._encrypt(str(tokens["access_token"])),
            encrypted_refresh_token=self._encrypt(refresh_token),
            access_expires_at=now + timedelta(seconds=int(tokens.get("expires_in", 3600))),
            refresh_expires_at=now
            + timedelta(seconds=int(tokens.get("x_refresh_token_expires_in", 8_726_400))),
            updated_at=now,
        )

    async def _token_request(
        self, client: httpx.AsyncClient, data: dict[str, str]
    ) -> dict[str, Any]:
        response = await client.post(
            self._settings.qbo_token_url,
            auth=(self._settings.qbo_client_id, self._settings.qbo_client_secret),
            data=data,
            headers={"Accept": "application/json"},
        )
        return self._checked_json(response, "token_exchange")

    async def _company_info(
        self, client: httpx.AsyncClient, realm_id: str, access_token: str
    ) -> dict[str, Any]:
        response = await client.get(
            (
                f"{self._settings.qbo_base_url}/company/{realm_id}"
                f"/companyinfo/{realm_id}"
            ),
            params={"minorversion": "75"},
            headers=self._bearer(access_token),
        )
        return self._checked_json(response, "company_info")["CompanyInfo"]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=20.0)

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    @staticmethod
    def _checked_json(response: httpx.Response, stage: str) -> dict[str, Any]:
        if response.is_error:
            raise QuickBooksIntegrationError(stage, response.status_code, "upstream_error")
        payload = response.json()
        if not isinstance(payload, dict):
            raise QboConnectionUnavailable("Unexpected QBO response")
        return payload

    def _encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise QboConnectionUnavailable("Stored QBO connection is unreadable") from exc

    @classmethod
    def _map_account_refs(
        cls, value: object, mapping: object
    ) -> object:
        if not isinstance(mapping, dict):
            raise QboAccountPreflightError("QBO account mapping is unavailable")
        if isinstance(value, Mapping):
            if set(value) == {"value"} and str(value["value"]) in ACCOUNT_DEFINITIONS:
                number = str(value["value"])
                if number not in mapping:
                    raise QboAccountPreflightError(
                        f"QBO account mapping missing {number}"
                    )
                return {"value": mapping[number]}
            return {key: cls._map_account_refs(item, mapping) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._map_account_refs(item, mapping) for item in value]
        return value
