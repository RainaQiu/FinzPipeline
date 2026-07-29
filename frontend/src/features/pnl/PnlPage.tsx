import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, TrendingUp, X } from "lucide-react";
import { api } from "../../api/client";
import { ErrorState, LoadingState, PageHeader } from "../../components/ui";
import type { PnlLine } from "../../types";
import { formatDate, formatMoney } from "../../utils/format";

const periods = [
  { label: "Q2 2026", start: "2026-04-01", end: "2026-06-30" },
  { label: "April", start: "2026-04-01", end: "2026-04-30" },
  { label: "May", start: "2026-05-01", end: "2026-05-31" },
  { label: "June", start: "2026-06-01", end: "2026-06-30" },
] as const;

export function PnlPage() {
  const [period, setPeriod] = useState<(typeof periods)[number]>(periods[0]);
  const [selected, setSelected] = useState<PnlLine | null>(null);
  const report = useQuery({
    queryKey: ["pnl", period.start, period.end],
    queryFn: () => api.pnl(period.start, period.end),
  });
  const drilldown = useQuery({
    queryKey: ["pnl-transactions", selected?.account_number, period.start, period.end],
    queryFn: () =>
      api.pnlTransactions(selected!.account_number, period.start, period.end),
    enabled: Boolean(selected),
  });

  return (
    <div className="page pnl-page">
      <PageHeader
        eyebrow="Cash-basis reporting"
        title="Internal P&L"
        description="Trace every summarized account line back to its classified bank activity."
        actions={
          <div className="period-tabs" role="group" aria-label="Reporting period">
            {periods.map((item) => (
              <button
                type="button"
                key={item.label}
                className={period.label === item.label ? "active" : undefined}
                aria-pressed={period.label === item.label}
                onClick={() => {
                  setPeriod(item);
                  setSelected(null);
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
      />

      {report.isLoading ? <LoadingState label="Loading P&L" /> : null}
      {report.isError ? <ErrorState error={report.error} /> : null}
      {report.data ? (
        <>
          <dl className="pnl-totals">
            <div>
              <dt>Revenue</dt>
              <dd>{formatMoney(report.data.totals.revenue_minor)}</dd>
            </div>
            <div>
              <dt>Gross profit</dt>
              <dd>{formatMoney(report.data.totals.gross_profit_minor)}</dd>
            </div>
            <div>
              <dt>Operating expenses</dt>
              <dd>{formatMoney(report.data.totals.operating_expenses_minor)}</dd>
            </div>
            <div className="emphasis">
              <dt>Net profit</dt>
              <dd>{formatMoney(report.data.totals.net_profit_minor)}</dd>
            </div>
          </dl>

          <div className="pnl-workspace">
            <section className="statement" aria-labelledby="statement-title">
              <div className="statement-heading">
                <div>
                  <p className="eyebrow">{period.label}</p>
                  <h2 id="statement-title">Profit and loss statement</h2>
                </div>
                <TrendingUp aria-hidden="true" />
              </div>
              <StatementSection
                title="Revenue"
                lines={report.data.revenue_lines}
                totalLabel="Total revenue"
                total={report.data.totals.revenue_minor}
                onSelect={setSelected}
              />
              <StatementSection
                title="Cost of goods sold"
                lines={report.data.cogs_lines}
                totalLabel="Total COGS"
                total={report.data.totals.cogs_minor}
                onSelect={setSelected}
              />
              <div className="statement-total major">
                <span>Gross profit</span>
                <strong>{formatMoney(report.data.totals.gross_profit_minor)}</strong>
              </div>
              <StatementSection
                title="Operating expenses"
                lines={report.data.operating_expense_lines}
                totalLabel="Total operating expenses"
                total={report.data.totals.operating_expenses_minor}
                onSelect={setSelected}
              />
              <div className="statement-total net">
                <span>Net profit</span>
                <strong>{formatMoney(report.data.totals.net_profit_minor)}</strong>
              </div>
            </section>

            {selected ? (
              <aside className="pnl-drilldown" aria-labelledby="drilldown-title">
                <div className="dialog-header">
                  <div>
                    <p className="eyebrow">Account drill-down</p>
                    <h2 id="drilldown-title">
                      {selected.account_number} · {selected.account_name}
                    </h2>
                  </div>
                  <button
                    className="icon-button"
                    type="button"
                    onClick={() => setSelected(null)}
                    aria-label="Close drill-down"
                  >
                    <X aria-hidden="true" />
                  </button>
                </div>
                <p className="drilldown-summary">
                  {selected.transaction_count} classified transaction
                  {selected.transaction_count === 1 ? "" : "s"} ·{" "}
                  {formatMoney(selected.total_minor)}
                </p>
                {drilldown.isLoading ? (
                  <LoadingState label="Loading account transactions" />
                ) : null}
                {drilldown.isError ? <ErrorState error={drilldown.error} /> : null}
                {drilldown.data ? (
                  <ul className="transaction-list">
                    {drilldown.data.items.map((transaction) => (
                      <li key={transaction.id}>
                        <span>
                          <strong>{transaction.description}</strong>
                          <small>{formatDate(transaction.transaction_date)}</small>
                        </span>
                        <strong>{formatMoney(transaction.amount_minor)}</strong>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </aside>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

function StatementSection({
  title,
  lines,
  totalLabel,
  total,
  onSelect,
}: {
  title: string;
  lines: PnlLine[];
  totalLabel: string;
  total: number;
  onSelect: (line: PnlLine) => void;
}) {
  return (
    <section className="statement-section">
      <h3>{title}</h3>
      {lines.length === 0 ? (
        <p className="statement-empty">No activity in this period.</p>
      ) : (
        lines.map((line) => (
          <button
            type="button"
            className="statement-line"
            key={line.account_number}
            onClick={() => onSelect(line)}
            aria-label={`Drill into ${line.account_number} ${line.account_name}`}
          >
            <span>
              <small>{line.account_number}</small>
              {line.account_name}
            </span>
            <span>
              {formatMoney(line.total_minor)}
              <ChevronRight aria-hidden="true" />
            </span>
          </button>
        ))
      )}
      <div className="statement-total">
        <span>{totalLabel}</span>
        <strong>{formatMoney(total)}</strong>
      </div>
    </section>
  );
}
