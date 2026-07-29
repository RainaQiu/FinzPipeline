const appDatabaseName = process.env.FINZ_MONGO_APP_DATABASE;
const appUsername = process.env.FINZ_MONGO_APP_USERNAME;
const appPassword = process.env.FINZ_MONGO_APP_PASSWORD;

if (!appDatabaseName || !appUsername || !appPassword) {
  throw new Error("Finz MongoDB application user variables are required.");
}

const appDatabase = db.getSiblingDB(appDatabaseName);
if (appDatabase.getUser(appUsername) === null) {
  appDatabase.createUser({
    user: appUsername,
    pwd: appPassword,
    roles: [
      { role: "readWrite", db: appDatabaseName },
      { role: "dbOwner", db: "finz_ledger_bridge_test" },
    ],
  });
}
