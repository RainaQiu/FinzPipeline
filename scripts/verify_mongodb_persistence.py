"""Write or verify one fixed marker used for named-volume restart checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from pymongo import MongoClient


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
MARKER_ID = "finz-test-volume-marker"


def _read_local_uri() -> str:
    with ENV_PATH.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            key, separator, value = line.rstrip("\r\n").partition("=")
            if separator and key.strip() == "FINZ_LOCAL_MONGODB_URI":
                return value
    raise RuntimeError("FINZ_LOCAL_MONGODB_URI is missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("write", "verify-clean"))
    action = parser.parse_args().action
    client = MongoClient(_read_local_uri(), serverSelectionTimeoutMS=5_000)
    collection = client["finz_ledger_bridge"]["finz_persistence_checks"]
    try:
        if action == "write":
            collection.replace_one(
                {"_id": MARKER_ID},
                {"_id": MARKER_ID, "kind": "finz-test", "retained": True},
                upsert=True,
            )
            print("Finz persistence marker written.")
            return 0
        marker = collection.find_one({"_id": MARKER_ID, "retained": True})
        if marker is None:
            print("Finz persistence marker was not found after restart.")
            return 2
        result = collection.delete_one({"_id": MARKER_ID})
        if result.deleted_count != 1:
            print("Finz persistence marker cleanup failed.")
            return 3
        print("Finz persistence marker survived restart and was removed.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

