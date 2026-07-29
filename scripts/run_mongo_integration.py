"""Run real local MongoDB tests without displaying credentials."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import argparse


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _read_local_uri() -> str:
    with ENV_PATH.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            key, separator, value = line.rstrip("\r\n").partition("=")
            if separator and key.strip() == "FINZ_LOCAL_MONGODB_URI":
                if not value:
                    break
                return value
    raise RuntimeError("FINZ_LOCAL_MONGODB_URI is missing; run the secret setup script")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="run the complete backend suite with real Mongo integration enabled",
    )
    run_all = parser.parse_args().all
    environment = os.environ.copy()
    environment["FINZ_MONGODB_URI"] = _read_local_uri()
    environment["FINZ_RUN_MONGO_INTEGRATION"] = "1"
    command = [sys.executable, "-m", "pytest"]
    if not run_all:
        command.extend(
            [
                "tests/integration/test_mongo_repositories.py",
                "tests/integration/test_mongo_persistence.py",
                "tests/integration/test_mongo_cloud_repositories.py",
            ]
        )
    command.append("-q")
    return subprocess.run(
        command,
        cwd=ROOT / "backend",
        env=environment,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
