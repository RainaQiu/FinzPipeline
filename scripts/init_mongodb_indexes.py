"""Create the Finz application MongoDB indexes idempotently."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.mongo import MongoUnitOfWork  # noqa: E402


def _read_local_uri() -> str:
    with (ROOT / ".env").open("r", encoding="utf-8") as env_file:
        for line in env_file:
            key, separator, value = line.rstrip("\r\n").partition("=")
            if separator and key.strip() == "FINZ_LOCAL_MONGODB_URI":
                return value
    raise RuntimeError("FINZ_LOCAL_MONGODB_URI is missing")


async def _initialize() -> None:
    uow = MongoUnitOfWork.from_uri(_read_local_uri(), "finz_ledger_bridge")
    async with uow:
        await uow.create_indexes()
    print("Finz MongoDB indexes are ready.")


if __name__ == "__main__":
    asyncio.run(_initialize())

