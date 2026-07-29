# Local MongoDB development

The local database is isolated to `127.0.0.1`, uses the named volume
`finz_mongodb_data`, and creates a separate read/write application user for
`finz_ledger_bridge`. It does not use MongoDB Atlas credentials.

## First-time setup

From `D:\MISM\Finz`:

```powershell
& .\.venv312\Scripts\python.exe scripts\ensure_local_mongodb_secrets.py
docker compose config --quiet
docker compose up -d mongodb
docker inspect --format "{{json .State.Health.Status}}" finz-mongodb
```

The setup script appends only missing `FINZ_MONGO_*` variables to the ignored
local `.env`; it never prints their values. `compose.yaml` contains no password.
Do not paste `.env` into a terminal or issue report.

Wait until the health value is `"healthy"`, then verify authentication without
putting credentials in command arguments:

```powershell
& .\.venv312\Scripts\python.exe scripts\mongosh_ping.py
& .\.venv312\Scripts\python.exe scripts\ensure_local_mongodb_test_role.py
& .\.venv312\Scripts\python.exe scripts\init_mongodb_indexes.py
```

## Repository integration tests

```powershell
& .\.venv312\Scripts\python.exe scripts\run_mongo_integration.py
& .\.venv312\Scripts\python.exe scripts\run_mongo_integration.py --all
```

Tests use and delete only the exact `finz_ledger_bridge_test` database. The app
user has `readWrite` only on the app database and `dbOwner` only on this test
database; it has no cross-database wildcard role. Unit and API tests continue to use the
in-memory repository unless MongoDB is explicitly composed into the app.

## Start, stop, and inspect

```powershell
docker compose up -d mongodb
docker compose stop mongodb
docker compose ps
docker volume inspect finz_mongodb_data
```

`docker compose stop mongodb` preserves the named volume. Do not use
`docker compose down -v`; that would delete local data. The container is named
`finz-mongodb` and carries `com.finz.project=ledger-bridge` labels.

If host port 27017 belongs to another process, do not stop it. Change only
`FINZ_MONGODB_PORT` and `FINZ_LOCAL_MONGODB_URI` in the ignored local `.env` to
use `27018`, then recreate this project container.

## Persistence verification

The repository reconnect test is part of the integration suite. A stronger
named-volume check can insert a marker into the dedicated
`finz_persistence_checks` collection, restart only `finz-mongodb`, verify the
same marker, and remove only that marker. Never remove unrelated containers,
volumes, databases, or collections.

```powershell
& .\.venv312\Scripts\python.exe scripts\verify_mongodb_persistence.py write
docker compose restart mongodb
# Wait for the health check to return healthy.
& .\.venv312\Scripts\python.exe scripts\verify_mongodb_persistence.py verify-clean
```
