import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, LockKeyhole, ShieldCheck } from "lucide-react";
import { api } from "../../api/client";
import { ErrorState, LoadingState, PageHeader, StatusBadge } from "../../components/ui";

export function QboPage() {
  const [accessCode, setAccessCode] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const status = useQuery({
    queryKey: ["qbo-status"],
    queryFn: api.qboStatus,
  });
  const plan = useMutation({
    mutationFn: () => api.planQboSync(),
  });
  const accounts = useQuery({
    queryKey: ["qbo-account-preflight"],
    queryFn: api.qboAccountPreflight,
    enabled: false,
  });
  const firstItemId = plan.data?.item_ids[0];
  const prewrite = useQuery({
    queryKey: ["qbo-prewrite", firstItemId],
    queryFn: () => api.qboPrewrite(firstItemId!),
    enabled: Boolean(firstItemId),
  });
  const execute = useMutation({
    mutationFn: async () => {
      const itemId = firstItemId;
      if (!itemId) throw new Error("Build a pending outbox plan first.");
      const grant = await api.issueDemoGrant(accessCode);
      return api.executeQboItem(itemId, grant.grant_token, confirmation);
    },
  });

  return (
    <div className="page qbo-page">
      <PageHeader
        eyebrow="QuickBooks Online"
        title="QBO Sync"
        description="Prepare an auditable outbox plan without authorizing external accounting writes."
        actions={
          <StatusBadge tone={status.data?.connected ? "success" : "review"}>
            {status.data?.connected ? "Real Sandbox read-only" : "Demo/local mode"}
          </StatusBadge>
        }
      />

      {status.isLoading ? <LoadingState label="Checking QBO mode" /> : null}
      {status.isError ? <ErrorState error={status.error} /> : null}
      {status.data ? (
        <div className="qbo-layout">
          <section className="execution-boundary" aria-labelledby="execution-title">
            <div className="boundary-icon">
              <LockKeyhole aria-hidden="true" />
            </div>
            <div>
              <p className="eyebrow">Execution boundary</p>
              <h2 id="execution-title">Writes require access + confirmation</h2>
              <p>
                Ordinary visitors can inspect plans. A Sandbox write additionally
                requires the emailed access code, exact confirmation, and a
                server-side enable flag that remains off by default.
              </p>
            </div>
            <dl className="boundary-facts">
              <div>
                <dt>Mode</dt>
                <dd>{status.data.mode === "sandbox_read_only" ? "Real Sandbox read" : "Demo/local"}</dd>
              </div>
              <div>
                <dt>Connected company</dt>
                <dd>{status.data.company_name ?? "Not connected"}</dd>
              </div>
              <div>
                <dt>Transaction write network</dt>
                <dd>
                  {status.data.transaction_write_network_accessed
                    ? "Attempt recorded"
                    : "No attempt recorded"}
                </dd>
              </div>
            </dl>
            <div className="network-note" role="status">
              <ShieldCheck aria-hidden="true" />
              <span>
                <strong>
                  {status.data.transaction_write_network_accessed
                    ? "A QBO Sandbox write attempt is recorded in this demo workspace."
                    : "No QBO transaction write network access has occurred."}
                </strong>
                {" "}
                OAuth and read-only verification may use QBO separately; this
                workspace only builds deterministic transaction payload previews.
              </span>
            </div>
            {!status.data.connected ? (
              <a
                className="button secondary full"
                href="/api/v1/integrations/qbo/connect"
              >
                Connect BrightFix QBO Sandbox
              </a>
            ) : (
              <>
                <button
                  className="button secondary full"
                  type="button"
                  disabled={accounts.isFetching}
                  onClick={() => accounts.refetch()}
                >
                  {accounts.isFetching
                    ? "Checking 21 accounts…"
                    : "Run 21-account preflight"}
                </button>
                {accounts.data ? (
                  <div className="plan-result" role="status">
                    <CheckCircle2 aria-hidden="true" />
                    <span>
                      <strong>{accounts.data.account_count} accounts ready.</strong>
                      {" "}
                      Utilities 6060 reuses QBO Id {accounts.data.mapping["6060"]}.
                    </span>
                  </div>
                ) : null}
                {accounts.isError ? <ErrorState error={accounts.error} /> : null}
              </>
            )}
          </section>

          <section className="outbox-planner" aria-labelledby="outbox-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Pending outbox</p>
                <h2 id="outbox-title">Plan a sync batch</h2>
              </div>
            </div>
            <div className="plan-flow" aria-label="Plan-only workflow">
              <span>Approved classifications</span>
              <ArrowRight aria-hidden="true" />
              <span>Validated journal payloads</span>
              <ArrowRight aria-hidden="true" />
              <span>Pending outbox</span>
            </div>
            {plan.isError ? <ErrorState error={plan.error} /> : null}
            {plan.data ? (
              <div className="plan-result" role="status">
                <CheckCircle2 aria-hidden="true" />
                <span>
                  <strong>{plan.data.planned_items} items planned</strong>
                  {" "}
                  Run {plan.data.id.slice(0, 8)} remains pending; writes are disabled.
                </span>
              </div>
            ) : null}
            <button
              className="button primary full"
              type="button"
              disabled={plan.isPending}
              onClick={() => plan.mutate()}
            >
              {plan.isPending ? "Planning batch…" : "Build pending outbox plan"}
            </button>
            <label className="field">
              <span>Interviewer access code</span>
              <input
                type="password"
                autoComplete="off"
                value={accessCode}
                onChange={(event) => setAccessCode(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Type: POST TO BRIGHTFIX QBO SANDBOX</span>
              <input
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </label>
            {execute.isError ? <ErrorState error={execute.error} /> : null}
            {execute.data ? (
              <div className="plan-result" role="status">
                <CheckCircle2 aria-hidden="true" />
                <strong>Sandbox item status: {execute.data.status}</strong>
              </div>
            ) : null}
            {prewrite.data ? (
              <dl className="boundary-facts" aria-label="First planned item preview">
                <div>
                  <dt>First entity</dt>
                  <dd>{prewrite.data.entity_type}</dd>
                </div>
                <div>
                  <dt>Amount</dt>
                  <dd>{prewrite.data.amount ?? "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Server write flag</dt>
                  <dd>{prewrite.data.writes_enabled ? "Enabled" : "Disabled"}</dd>
                </div>
              </dl>
            ) : null}
            {prewrite.isError ? <ErrorState error={prewrite.error} /> : null}
            <button
              className="button secondary full"
              type="button"
              disabled={
                !prewrite.data ||
                !accessCode ||
                confirmation !== "POST TO BRIGHTFIX QBO SANDBOX" ||
                execute.isPending
              }
              onClick={() => execute.mutate()}
            >
              {execute.isPending ? "Submitting…" : "Submit first planned item to Sandbox"}
            </button>
          </section>
        </div>
      ) : null}
    </div>
  );
}
