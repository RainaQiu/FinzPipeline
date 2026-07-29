"""Run an authenticated mongosh ping without exposing credentials."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
MONGOSH_ROOT = Path(r"D:\Mysoft\mongosh-2.9.2-win32-x64")
ALLOWED_KEYS = {
    "FINZ_MONGO_ROOT_USERNAME",
    "FINZ_MONGO_ROOT_PASSWORD",
    "FINZ_MONGODB_PORT",
}


def _mongo_environment() -> dict[str, str]:
    environment = os.environ.copy()
    with ENV_PATH.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            key, separator, value = line.rstrip("\r\n").partition("=")
            if separator and key.strip() in ALLOWED_KEYS:
                environment[key.strip()] = value
    if not environment.get("FINZ_MONGO_ROOT_USERNAME") or not environment.get(
        "FINZ_MONGO_ROOT_PASSWORD"
    ):
        raise RuntimeError("Finz local MongoDB root variables are missing")
    environment["FINZ_MONGO_PING_HOST"] = "127.0.0.1"
    return environment


def main() -> int:
    matches = list(MONGOSH_ROOT.rglob("mongosh.exe"))
    if not matches:
        raise RuntimeError("mongosh.exe was not found under the configured directory")
    javascript = """
const connection = new Mongo(`mongodb://${process.env.FINZ_MONGO_PING_HOST}:${process.env.FINZ_MONGODB_PORT || "27017"}`);
const adminDatabase = connection.getDB("admin");
if (!adminDatabase.auth(process.env.FINZ_MONGO_ROOT_USERNAME, process.env.FINZ_MONGO_ROOT_PASSWORD)) {
  throw new Error("authentication failed");
}
const result = adminDatabase.runCommand({ ping: 1 });
print(EJSON.stringify({ ok: result.ok }));
quit(result.ok === 1 ? 0 : 2);
""".strip()
    completed = subprocess.run(
        [str(matches[0]), "--quiet", "--nodb", "--eval", javascript],
        env=_mongo_environment(),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

