"""Append missing Finz-local Mongo variables to .env without printing values."""

from __future__ import annotations

from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
REQUIRED_DEFAULTS = {
    "FINZ_MONGO_ROOT_USERNAME": "finz_root",
    "FINZ_MONGO_APP_USERNAME": "finz_app",
    "FINZ_MONGO_APP_DATABASE": "finz_ledger_bridge",
    "FINZ_MONGODB_PORT": "27017",
}
PASSWORD_KEYS = ("FINZ_MONGO_ROOT_PASSWORD", "FINZ_MONGO_APP_PASSWORD")
LOCAL_KEYS = {
    *REQUIRED_DEFAULTS,
    *PASSWORD_KEYS,
    "FINZ_LOCAL_MONGODB_URI",
}


def _local_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    with ENV_PATH.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            key, separator, value = line.rstrip("\r\n").partition("=")
            if separator and key.strip() in LOCAL_KEYS:
                values[key.strip()] = value
    return values


def main() -> None:
    values = _local_values()
    additions: dict[str, str] = {}
    for key, default in REQUIRED_DEFAULTS.items():
        if not values.get(key):
            additions[key] = default
    for key in PASSWORD_KEYS:
        if not values.get(key):
            additions[key] = token_urlsafe(32)
    resolved = {**values, **additions}
    if not values.get("FINZ_LOCAL_MONGODB_URI"):
        username = quote(resolved["FINZ_MONGO_APP_USERNAME"], safe="")
        password = quote(resolved["FINZ_MONGO_APP_PASSWORD"], safe="")
        port = resolved["FINZ_MONGODB_PORT"]
        database = resolved["FINZ_MONGO_APP_DATABASE"]
        additions["FINZ_LOCAL_MONGODB_URI"] = (
            f"mongodb://{username}:{password}@127.0.0.1:{port}/{database}"
            f"?authSource={quote(database, safe='')}"
        )
    if additions:
        needs_leading_newline = ENV_PATH.exists() and ENV_PATH.stat().st_size > 0
        with ENV_PATH.open("a", encoding="utf-8", newline="\n") as env_file:
            if needs_leading_newline:
                env_file.write("\n")
            env_file.write("# Finz local MongoDB (generated; do not commit)\n")
            for key, value in additions.items():
                env_file.write(f"{key}={value}\n")
    print("Finz local MongoDB variables are ready (values not displayed).")


if __name__ == "__main__":
    main()
