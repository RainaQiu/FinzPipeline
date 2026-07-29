import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Scale } from "lucide-react";
import { api } from "../../api/client";
import { ErrorState, PageHeader, StatusBadge } from "../../components/ui";
import { formatMoney, titleCase } from "../../utils/format";

export function ReconciliationPage() {
  const [startDate, setStartDate] = useState("2026-04-01");
  const [endDate, setEndDate] = useState("2026-06-30");
  const [qboJson, setQboJson] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const reconciliation = useMutation({
    mutationFn: (report: Record<string, unknown>) =>
      api.reconcile(startDate, endDate, report),
  });

  const submit = () => {
    try {
      const report = JSON.parse(qboJson) as Record<string, unknown>;
      setParseError(null);
      reconciliation.mutate(report);
    } catch {
      setParseError("Enter a valid QBO Profit and Loss JSON payload.");
    }
  };

  return (
    <div className="page reconciliation-page">
      <PageHeader
        eyebrow="Zero-tolerance check"
        title="Reconciliation"
        description="Compare the internal cash-basis P&L with a locally supplied QBO report."
        actions={
          reconciliation.data ? (
            <StatusBadge
              tone={reconciliation.data.status === "matched" ? "success" : "danger"}
            >
              {reconciliation.data.status === "matched" ? "Matched" : "Mismatch"}
            </StatusBadge>
          ) : undefined
        }
      />

      <div className="reconciliation-layout">
        <section className="reconciliation-form" aria-labelledby="reconcile-input-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Local input</p>
              <h2 id="reconcile-input-title">QBO report payload</h2>
            </div>
            <Scale aria-hidden="true" />
          </div>
          <div className="date-row">
            <label className="field">
              <span>Start date</span>
              <input
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </label>
            <label className="field">
              <span>End date</span>
              <input
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </label>
          </div>
          <label className="field">
            <span>QBO Profit and Loss JSON</span>
            <textarea
              className="code-input"
              value={qboJson}
              onChange={(event) => setQboJson(event.target.value)}
              placeholder='{"Rows":{"Row":[...]}}'
              rows={12}
            />
          </label>
          {parseError ? (
            <div className="state-message error-state" role="alert">
              <AlertTriangle aria-hidden="true" />
              {parseError}
            </div>
          ) : null}
          {reconciliation.isError ? <ErrorState error={reconciliation.error} /> : null}
          <button
            className="button primary full"
            type="button"
            disabled={!qboJson.trim() || reconciliation.isPending}
            onClick={submit}
          >
            {reconciliation.isPending
              ? "Reconciling locally…"
              : "Run local reconciliation"}
          </button>
          <p className="form-footnote">
            The payload stays in this request. No QuickBooks network call is made.
          </p>
        </section>

        <section className="difference-region" aria-labelledby="difference-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Comparison result</p>
              <h2 id="difference-title">Account differences</h2>
            </div>
          </div>
          {!reconciliation.data ? (
            <div className="empty-comparison">
              <Scale aria-hidden="true" />
              <strong>No comparison yet</strong>
              <span>Submit a local QBO report to compare account totals.</span>
            </div>
          ) : reconciliation.data.lines.length === 0 ? (
            <div className="empty-comparison success">
              <CheckCircle2 aria-hidden="true" />
              <strong>Matched</strong>
              <span>No account differences were found.</span>
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Account</th>
                    <th scope="col">Internal</th>
                    <th scope="col">QBO</th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {reconciliation.data.lines.map((line) => {
                    const mismatch = line.difference_minor !== 0;
                    return (
                      <tr key={line.account_number}>
                        <td>
                          <span className="account-status">
                            <strong>{line.account_number}</strong>
                            {" "}
                            <small>{titleCase(line.status)}</small>
                          </span>
                        </td>
                        <td>{formatMoney(line.internal_minor)}</td>
                        <td>{formatMoney(line.qbo_minor)}</td>
                        <td>
                          <span className="reconciliation-result">
                            <StatusBadge tone={mismatch ? "danger" : "success"}>
                              {mismatch ? "Mismatch" : "Matched"}
                            </StatusBadge>
                            <span className={mismatch ? "difference-value" : undefined}>
                              Difference: {formatMoney(line.difference_minor)}
                            </span>
                            {line.diagnostic_candidates.map((candidate) => (
                              <small key={candidate}>{candidate}</small>
                            ))}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
