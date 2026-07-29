import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, FileSpreadsheet, UploadCloud } from "lucide-react";
import { api } from "../../api/client";
import { ErrorState, PageHeader, StatusBadge } from "../../components/ui";
import type { UploadMapping } from "../../types";

const defaultMapping: UploadMapping = {
  sheet_name: "Raw Bank Transactions",
  header_row: 4,
  columns: {
    transaction_id: "Bank Transaction ID",
    transaction_date: "Transaction Date",
    posted_date: "Posted Date",
    description: "Description",
    amount: "Amount (USD)",
    currency: "Currency",
    bank_account: "Bank Account",
  },
  source_file_column: "Source File",
};

const mappingFields: Array<{
  key: keyof UploadMapping["columns"];
  label: string;
}> = [
  { key: "transaction_id", label: "Transaction ID" },
  { key: "transaction_date", label: "Transaction date" },
  { key: "posted_date", label: "Posted date" },
  { key: "description", label: "Description" },
  { key: "amount", label: "Amount" },
  { key: "currency", label: "Currency" },
  { key: "bank_account", label: "Bank account" },
];

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<UploadMapping>(defaultMapping);
  const upload = useMutation({
    mutationFn: (source: File) => api.upload(source),
  });
  const process = useMutation({
    mutationFn: () => api.processUpload(upload.data!.id, mapping),
  });

  return (
    <div className="page upload-page">
      <PageHeader
        eyebrow="Source ingestion"
        title="Upload & Mapping"
        description="Stage a bank export, verify its columns, then run the deterministic ledger pipeline."
      />

      <div className="step-rail" aria-label="Upload progress">
        <span className={!upload.data ? "current" : "complete"}>1 · Source file</span>
        <span className={upload.data && !process.data ? "current" : process.data ? "complete" : ""}>
          2 · Column mapping
        </span>
        <span className={process.data ? "complete" : ""}>3 · Quality result</span>
      </div>

      {!upload.data ? (
        <section className="upload-stage" aria-labelledby="source-file-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Step 1</p>
              <h2 id="source-file-title">Choose a source file</h2>
            </div>
            <StatusBadge>CSV or XLSX · 20 MB max</StatusBadge>
          </div>
          <label className="drop-zone">
            <input
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              aria-label="Choose source file"
              onChange={(event) => {
                const nextFile = event.target.files?.[0] ?? null;
                setFile(nextFile);
                upload.reset();
              }}
            />
            <UploadCloud aria-hidden="true" />
            <span>
              <strong>{file ? file.name : "No file selected"}</strong>
              <small>
                {file
                  ? `${(file.size / 1024).toFixed(1)} KB · Ready to stage`
                  : "Choose a BrightFix bank transaction export to begin."}
              </small>
            </span>
          </label>
          {upload.isError ? <ErrorState error={upload.error} /> : null}
          <div className="stage-actions">
            <button
              className="button primary"
              type="button"
              disabled={!file || upload.isPending}
              onClick={() => {
                if (file) upload.mutate(file);
              }}
            >
              <UploadCloud aria-hidden="true" />
              {upload.isPending ? "Uploading…" : "Upload and preview"}
            </button>
          </div>
        </section>
      ) : null}

      {upload.data && !process.data ? (
        <section className="mapping-stage" aria-labelledby="mapping-title">
          <div className="file-summary">
            <FileSpreadsheet aria-hidden="true" />
            <div>
              <strong>{upload.data.filename}</strong>
              <span>
                {(upload.data.size_bytes / 1024).toFixed(1)} KB · Upload staged locally
              </span>
            </div>
            <StatusBadge tone="success">Ready to map</StatusBadge>
          </div>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2 id="mapping-title">Confirm column mapping</h2>
            </div>
          </div>
          <div className="mapping-meta">
            <label className="field">
              <span>Worksheet</span>
              <input
                value={mapping.sheet_name ?? ""}
                onChange={(event) =>
                  setMapping((current) => ({ ...current, sheet_name: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Header row</span>
              <input
                type="number"
                min="1"
                value={mapping.header_row}
                onChange={(event) =>
                  setMapping((current) => ({
                    ...current,
                    header_row: Number(event.target.value),
                  }))
                }
              />
            </label>
          </div>
          <div className="mapping-grid">
            {mappingFields.map(({ key, label }) => (
              <label className="field mapping-field" key={key}>
                <span>{label}</span>
                <input
                  value={mapping.columns[key] ?? ""}
                  onChange={(event) =>
                    setMapping((current) => ({
                      ...current,
                      columns: { ...current.columns, [key]: event.target.value },
                    }))
                  }
                />
              </label>
            ))}
          </div>
          {process.isError ? <ErrorState error={process.error} /> : null}
          <div className="stage-actions split">
            <button
              className="button secondary"
              type="button"
              onClick={() => {
                upload.reset();
                setFile(null);
              }}
            >
              Replace file
            </button>
            <button
              className="button primary"
              type="button"
              disabled={process.isPending}
              onClick={() => process.mutate()}
            >
              {process.isPending ? "Processing…" : "Confirm mapping & process"}
            </button>
          </div>
        </section>
      ) : null}

      {process.data ? (
        <section className="quality-stage" aria-labelledby="quality-title">
          <div className="quality-heading">
            <CheckCircle2 aria-hidden="true" />
            <div>
              <p className="eyebrow">Step 3 · Completed</p>
              <h2 id="quality-title">Pipeline quality report</h2>
              <p>All rows were retained in lineage; duplicate candidates were isolated.</p>
            </div>
          </div>
          <dl className="metric-strip">
            <div>
              <dt>Raw rows</dt>
              <dd>{process.data.counts.raw}</dd>
            </div>
            <div>
              <dt>Unique</dt>
              <dd>{process.data.counts.unique}</dd>
            </div>
            <div>
              <dt>Duplicates</dt>
              <dd>{process.data.counts.duplicates}</dd>
            </div>
            <div>
              <dt>Transfer pairs</dt>
              <dd>{process.data.counts.transfer_pairs}</dd>
            </div>
            <div>
              <dt>Classified</dt>
              <dd>{process.data.counts.classified}</dd>
            </div>
          </dl>
          <div className="quality-note" role="status">
            <strong>
              {process.data.counts.raw} rows in · {process.data.counts.unique} reviewable
              transactions out
            </strong>
            <span>
              {process.data.counts.duplicates} exact duplicates and{" "}
              {process.data.counts.transfer_pairs} transfer pairs identified.
            </span>
          </div>
        </section>
      ) : null}
    </div>
  );
}
