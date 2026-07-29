import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, LockKeyhole, ShieldCheck } from "lucide-react";
import { api } from "../../api/client";
import { ErrorState, LoadingState, PageHeader, StatusBadge } from "../../components/ui";

export function QboPage() {
  const [realmId, setRealmId] = useState("sandbox-realm");
  const status = useQuery({
    queryKey: ["qbo-status"],
    queryFn: api.qboStatus,
  });
  const plan = useMutation({
    mutationFn: () => api.planQboSync(realmId),
  });

  return (
    <div className="page qbo-page">
      <PageHeader
        eyebrow="QuickBooks Online"
        title="QBO Sync"
        description="Prepare an auditable outbox plan without authorizing external accounting writes."
        actions={<StatusBadge tone="review">Plan-only mode</StatusBadge>}
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
              <h2 id="execution-title">Writes disabled</h2>
              <p>
                Approved journal entries can be prepared as a pending outbox plan,
                but they cannot be posted or retried.
              </p>
            </div>
            <dl className="boundary-facts">
              <div>
                <dt>Mode</dt>
                <dd>Plan only</dd>
              </div>
              <div>
                <dt>Execution authorized</dt>
                <dd>No</dd>
              </div>
              <div>
                <dt>Transaction write network</dt>
                <dd>No</dd>
              </div>
            </dl>
            <div className="network-note" role="status">
              <ShieldCheck aria-hidden="true" />
              <span>
                <strong>No QBO transaction write network access has occurred.</strong>
                {" "}
                OAuth and read-only verification may use QBO separately; this
                workspace only builds deterministic transaction payload previews.
              </span>
            </div>
          </section>

          <section className="outbox-planner" aria-labelledby="outbox-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Pending outbox</p>
                <h2 id="outbox-title">Plan a sync batch</h2>
              </div>
            </div>
            <label className="field">
              <span>QBO realm ID</span>
              <input
                value={realmId}
                onChange={(event) => setRealmId(event.target.value)}
                placeholder="sandbox-realm"
              />
            </label>
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
              disabled={!realmId.trim() || plan.isPending}
              onClick={() => plan.mutate()}
            >
              {plan.isPending ? "Planning batch…" : "Build pending outbox plan"}
            </button>
          </section>
        </div>
      ) : null}
    </div>
  );
}
