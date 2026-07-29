import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbook = await SpreadsheetFile.importXlsx(
  await FileBlob.load("Finz Accounting Data Engineering Challenge Dataset.xlsx")
);
const sheet = workbook.worksheets.getItem("Raw Bank Transactions");
const rows = sheet.getRange("A5:H204").values.filter((r) => r[1]);

const ids = new Map();
for (const row of rows) {
  const id = String(row[1]);
  ids.set(id, (ids.get(id) || 0) + 1);
}
const duplicateIds = [...ids.entries()].filter(([, count]) => count > 1);
const uniqueRows = [];
const seen = new Set();
for (const row of rows) {
  if (seen.has(String(row[1]))) continue;
  seen.add(String(row[1]));
  uniqueRows.push(row);
}

const byMonth = {};
const byAccount = {};
const sourceFiles = new Set();
for (const row of uniqueRows) {
  const [source, , dateValue, , description, amount, , bankAccount] = row;
  sourceFiles.add(String(source));
  const date = dateValue instanceof Date ? dateValue : new Date(Math.round((Number(dateValue) - 25569) * 86400 * 1000));
  const month = date.toISOString().slice(0, 7);
  byMonth[month] ??= { count: 0, inflow: 0, outflow: 0 };
  byMonth[month].count += 1;
  if (Number(amount) >= 0) byMonth[month].inflow += Number(amount);
  else byMonth[month].outflow += Number(amount);
  byAccount[bankAccount] ??= { count: 0, net: 0 };
  byAccount[bankAccount].count += 1;
  byAccount[bankAccount].net += Number(amount);
}

const special = {
  transfer: uniqueRows.filter((r) => /TRANSFER TO TAX RESERVE|TRANSFER FROM OPERATING/i.test(String(r[4]))),
  owner: uniqueRows.filter((r) => /OWNER CAPITAL|OWNER DRAW/i.test(String(r[4]))),
  refund: uniqueRows.filter((r) => /REFUND TO/i.test(String(r[4]))),
  fixedAsset: uniqueRows.filter((r) => /COMMERCIAL TOOL PACKAGE/i.test(String(r[4]))),
};

console.log(JSON.stringify({
  rawRows: rows.length,
  uniqueTransactionIds: ids.size,
  duplicateExtraRows: rows.length - ids.size,
  duplicateIdCount: duplicateIds.length,
  duplicateIds,
  sourceFileCount: sourceFiles.size,
  sourceFiles: [...sourceFiles],
  byMonth,
  byAccount,
  specialCounts: Object.fromEntries(Object.entries(special).map(([k, v]) => [k, v.length])),
  specialTransactions: Object.fromEntries(Object.entries(special).map(([k, v]) => [k, v.map((r) => ({id:r[1], description:r[4], amount:r[5], account:r[7]}))])),
}, null, 2));
