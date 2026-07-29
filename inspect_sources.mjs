import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "Finz Accounting Data Engineering Challenge Dataset.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const overview = await workbook.inspect({
  kind: "workbook,sheet,table,region",
  maxChars: 20000,
  tableMaxRows: 20,
  tableMaxCols: 20,
  tableMaxCellChars: 200,
});
console.log(overview.ndjson);

await fs.mkdir("tmp/sheets", { recursive: true });
const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
console.log("SHEETS");
console.log(sheets.ndjson);

for (const line of sheets.ndjson.split(/\r?\n/).filter(Boolean)) {
  const record = JSON.parse(line);
  const name = record.name;
  if (!name) continue;
  const region = await workbook.inspect({
    kind: "region",
    sheetId: name,
    range: "A1:Z200",
    maxChars: 30000,
    tableMaxRows: 200,
    tableMaxCols: 26,
    tableMaxCellChars: 300,
  });
  console.log(`REGION ${name}`);
  console.log(region.ndjson);
  const image = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1.5, format: "png" });
  await fs.writeFile(`tmp/sheets/${name.replace(/[<>:"/\\|?*]/g, "_")}.png`, new Uint8Array(await image.arrayBuffer()));
}
