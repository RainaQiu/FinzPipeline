"""Short-lived one-time bearer grants for protected demo operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from typing import Awaitable, Callable

from pydantic import SecretStr

from app.domain.demo import DemoGrant
from app.repositories.protocols import UnitOfWork


GRANT_TTL = timedelta(minutes=15)
INVALID_ATTEMPT_DELAY_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class IssuedDemoGrant:
    token: str = field(repr=False)
    expires_in_seconds: int


class DemoAccessGrantService:
    """Issue and atomically consume opaque, short-lived demo grants."""

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        *,
        access_code: SecretStr | None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._access_code = access_code
        self._sleeper = sleeper
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (lambda: token_urlsafe(32))

    async def issue(self, presented_code: str) -> IssuedDemoGrant | None:
        expected = (
            self._access_code.get_secret_value()
            if self._access_code is not None
            else ""
        )
        presented_digest = sha256(presented_code.encode("utf-8")).digest()
        expected_digest = sha256(expected.encode("utf-8")).digest()
        if not expected or not compare_digest(presented_digest, expected_digest):
            await self._sleeper(INVALID_ATTEMPT_DELAY_SECONDS)
            return None

        now = self._clock()
        token = f"finz_demo_{self._token_factory()}"
        expires_at = now + GRANT_TTL
        await self._unit_of_work.demo_grants.issue(
            DemoGrant(
                token_hash=_token_hash(token),
                created_at=now,
                expires_at=expires_at,
            )
        )
        return IssuedDemoGrant(
            token=token,
            expires_in_seconds=int(GRANT_TTL.total_seconds()),
        )

    async def consume(self, token: str, *, now: datetime | None = None) -> bool:
        grant = await self._unit_of_work.demo_grants.consume_valid(
            _token_hash(token),
            now=now or self._clock(),
        )
        return grant is not None


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
