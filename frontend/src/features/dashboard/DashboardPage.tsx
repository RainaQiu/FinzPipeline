import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CircleCheckBig,
  FileClock,
  LockKeyhole,
  ShieldAlert,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { ErrorState, PageHeader, StatusBadge } from "../../components/ui";

export function DashboardPage() {
  const reviewQueue = useQuery({
    queryKey: ["dashboard-review-queue"],
    queryFn: () => api.transactions({ approval: "suggested" }),
  });
  const qbo = useQuery({
    queryKey: ["qbo-status"],
    queryFn: api.qboStatus,
  });

  const highRisk =
    reviewQueue.data?.items.filter((transaction) => transaction.risk === "high")
      .length ?? 0;
  const workspaceStatus =
    reviewQueue.isError || qbo.isError
      ? { tone: "danger" as const, label: "Workspace status unavailable" }
      : reviewQueue.isSuccess && qbo.isSuccess
        ? { tone: "success" as const, label: "Local workspace ready" }
        : { tone: "neutral" as const, label: "Checking workspace" };

  return (
    <div className="page dashboard-page">
      <PageHeader
        eyebrow="Accounting control center"
        title="Review readiness"
        description="Move bank activity from staged source data to a traceable, approved accounting plan."
        actions={
          <StatusBadge tone={workspaceStatus.tone}>
            {workspaceStatus.label}
          </StatusBadge>
        }
      />

      {reviewQueue.isError ? <ErrorState error={reviewQueue.error} /> : null}
      {qbo.isError ? <ErrorState error={qbo.error} /> : null}
      <dl className="dashboard-metrics">
        <div>
          <dt>Suggested transactions</dt>
          <dd>{reviewQueue.data?.total ?? "—"}</dd>
          <span>Awaiting a human decision</span>
        </div>
        <div>
          <dt>High-risk items</dt>
          <dd>{reviewQueue.isSuccess ? highRisk : "—"}</dd>
          <span>Need evidence review</span>
        </div>
        <div>
          <dt>QBO execution</dt>
          <dd>{qbo.isError ? "Unknown" : qbo.data ? "Disabled" : "—"}</dd>
          <span>Plan-only safety boundary</span>
        </div>
      </dl>

      <div className="dashboard-layout">
        <section className="workflow-panel" aria-labelledby="workflow-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Current workflow</p>
              <h2 id="workflow-title">Close the review loop</h2>
            </div>
          </div>
          <ol className="workflow-list">
            <li>
              <span className="workflow-icon complete">
                <CircleCheckBig aria-hidden="true" />
              </span>
              <div>
                <strong>Upload and normalize source data</strong>
                <span>Mapping preserves raw-row lineage.</span>
              </div>
              <Link to="/upload">Open upload</Link>
            </li>
            <li>
              <span className="workflow-icon review">
                <ShieldAlert aria-hidden="true" />
              </span>
              <div>
                <strong>Review classification risk</strong>
                <span>
                  {reviewQueue.data?.total ?? "—"} suggested transactions remain.
                </span>
              </div>
              <Link to="/review">Open queue</Link>
            </li>
            <li>
              <span className="workflow-icon">
                <FileClock aria-hidden="true" />
              </span>
              <div>
                <strong>Inspect internal P&amp;L</strong>
                <span>Drill into account totals before reconciliation.</span>
              </div>
              <Link to="/pnl">Open report</Link>
            </li>
          </ol>
        </section>

        <aside className="control-panel" aria-labelledby="control-title">
          <div className="control-heading">
            <LockKeyhole aria-hidden="true" />
            <div>
              <p className="eyebrow">Control boundary</p>
              <h2 id="control-title">External writes stay off</h2>
            </div>
          </div>
          <p>
            This implementation may prepare QBO journal payloads, but it does not
            authorize posting, retries, or transaction-write network execution.
          </p>
          <dl>
            <div>
              <dt>Execution authorized</dt>
              <dd>No</dd>
            </div>
            <div>
              <dt>Transaction write network</dt>
              <dd>No</dd>
            </div>
          </dl>
          <Link className="button secondary full" to="/qbo">
            Inspect pending outbox
            <ArrowRight aria-hidden="true" />
          </Link>
        </aside>
      </div>
    </div>
  );
}
