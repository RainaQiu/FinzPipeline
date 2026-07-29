import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, RefObject } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Check, Filter, Search, X } from "lucide-react";
import { api, type TransactionFilters } from "../../api/client";
import { ErrorState, LoadingState, PageHeader, StatusBadge } from "../../components/ui";
import type {
  Classification,
  Transaction,
  TransactionPage,
  TransactionType,
} from "../../types";
import { formatDate, formatMoney, titleCase } from "../../utils/format";

const accountOptions = [
  ["1000", "Operating Checking"],
  ["1010", "Tax Reserve"],
  ["1500", "Tools & Equipment"],
  ["3000", "Owner's Equity"],
  ["4000", "Repair Service Revenue"],
  ["4010", "Installation Revenue"],
  ["4020", "Maintenance Plan Revenue"],
  ["4100", "Customer Refunds"],
  ["5000", "Materials & Supplies"],
  ["5010", "Subcontractor Costs"],
  ["6000", "Payroll Expense"],
  ["6010", "Rent Expense"],
  ["6020", "Vehicle & Fuel"],
  ["6030", "Software & Subscriptions"],
  ["6040", "Marketing & Advertising"],
  ["6050", "Insurance Expense"],
  ["6060", "Utilities"],
  ["6070", "Professional Fees"],
  ["6080", "Bank Fees"],
  ["6090", "Office & General"],
  ["6100", "Repairs & Maintenance"],
] as const;

const transactionTypes: TransactionType[] = [
  "revenue",
  "cogs",
  "operating_expense",
  "refund",
  "transfer",
  "owner_activity",
  "fixed_asset",
];

const columnHelper = createColumnHelper<Transaction>();

export function ReviewPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<TransactionFilters>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const correctionTriggerRef = useRef<HTMLButtonElement>(null);

  const query = useQuery({
    queryKey: ["transactions", filters],
    queryFn: () => api.transactions(filters),
  });
  const selected =
    query.data?.items.find((transaction) => transaction.id === selectedId) ?? null;

  const updateClassification = (classification: Classification) => {
    queryClient.setQueryData<TransactionPage>(
      ["transactions", filters],
      (current) =>
        current
          ? {
              ...current,
              items: current.items.map((transaction) =>
                transaction.id === classification.transaction_id
                  ? {
                      ...transaction,
                      classification,
                      risk: classification.needs_review ? "high" : "low",
                    }
                  : transaction,
              ),
            }
          : current,
    );
    void queryClient.invalidateQueries({ queryKey: ["transactions"] });
  };

  const columns = useMemo(
    () => [
      columnHelper.accessor("transaction_date", {
        header: "Date",
        cell: (info) => formatDate(info.getValue()),
      }),
      columnHelper.accessor("description", {
        header: "Description",
        cell: (info) => {
          const transaction = info.row.original;
          return (
            <button
              className="row-select"
              type="button"
              onClick={() => setSelectedId(transaction.id)}
              aria-label={`Review ${transaction.description}`}
            >
              <strong>{transaction.description}</strong>
              <small>{transaction.bank_transaction_id}</small>
            </button>
          );
        },
      }),
      columnHelper.accessor("amount_minor", {
        header: "Amount",
        cell: (info) => (
          <span className={info.getValue() < 0 ? "money outflow" : "money"}>
            {formatMoney(info.getValue(), info.row.original.currency)}
          </span>
        ),
      }),
      columnHelper.display({
        id: "category",
        header: "Category",
        cell: ({ row }) =>
          row.original.classification
            ? `${row.original.classification.account_number} · ${titleCase(
                row.original.classification.transaction_type,
              )}`
            : "Unclassified",
      }),
      columnHelper.display({
        id: "confidence",
        header: "Confidence",
        cell: ({ row }) =>
          row.original.classification
            ? `${(row.original.classification.confidence_basis_points / 100).toFixed(
                2,
              )}% confidence`
            : "Not available",
      }),
      columnHelper.accessor("risk", {
        header: "Risk",
        cell: (info) => (
          <StatusBadge tone={info.getValue() === "high" ? "review" : "success"}>
            {titleCase(info.getValue())} risk
          </StatusBadge>
        ),
      }),
      columnHelper.display({
        id: "status",
        header: "Status",
        cell: ({ row }) => {
          const status = row.original.classification?.approval_status ?? "unclassified";
          return (
            <StatusBadge tone={status === "approved" ? "success" : "neutral"}>
              {titleCase(status)}
            </StatusBadge>
          );
        },
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: query.data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="page review-page">
      <PageHeader
        eyebrow="Human review queue"
        title="Transaction Review"
        description="Resolve classification risk before anything reaches the accounting outbox."
        actions={
          <div className="review-count" role="status">
            <strong>{query.data?.total ?? 0}</strong>
            <span>transactions</span>
          </div>
        }
      />

      <div className="filter-bar" aria-label="Transaction filters">
        <label className="search-field">
          <span className="sr-only">Search transactions</span>
          <Search aria-hidden="true" />
          <input
            type="search"
            placeholder="Search description or bank ID"
            value={filters.search ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, search: event.target.value }))
            }
          />
        </label>
        <Filter aria-hidden="true" className="filter-icon" />
        <label>
          <span className="sr-only">Month</span>
          <input
            type="month"
            value={filters.month ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, month: event.target.value }))
            }
          />
        </label>
        <label>
          <span className="sr-only">Account filter</span>
          <select
            aria-label="Account filter"
            value={filters.account ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, account: event.target.value }))
            }
          >
            <option value="">All accounts</option>
            {accountOptions.map(([number, name]) => (
              <option key={number} value={number}>
                {number} · {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Duplicate status filter</span>
          <select
            aria-label="Duplicate status filter"
            value={filters.duplicate ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                duplicate: event.target.value,
              }))
            }
          >
            <option value="">All duplicate states</option>
            <option value="unique">Unique</option>
            <option value="possible_duplicate">Possible duplicate</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Approval status</span>
          <select
            value={filters.approval ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, approval: event.target.value }))
            }
          >
            <option value="">All statuses</option>
            <option value="suggested">Suggested</option>
            <option value="approved">Approved</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Risk</span>
          <select
            value={filters.risk ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, risk: event.target.value }))
            }
          >
            <option value="">All risk</option>
            <option value="high">High risk</option>
            <option value="low">Low risk</option>
          </select>
        </label>
        {Object.values(filters).some(Boolean) ? (
          <button className="button ghost" type="button" onClick={() => setFilters({})}>
            <X aria-hidden="true" />
            Clear
          </button>
        ) : null}
      </div>

      <div className="review-workspace">
        <section className="table-region" aria-labelledby="review-table-title">
          <h2 id="review-table-title" className="sr-only">
            Transactions awaiting review
          </h2>
          {query.isLoading ? <LoadingState label="Loading transactions" /> : null}
          {query.isError ? <ErrorState error={query.error} /> : null}
          {query.isSuccess && (query.data?.items.length ?? 0) === 0 ? (
            <div className="state-message">No transactions match these filters.</div>
          ) : null}
          {query.isSuccess && (query.data?.items.length ?? 0) > 0 ? (
            <div className="table-scroll">
              <table>
                <thead>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <tr key={headerGroup.id}>
                      {headerGroup.headers.map((header) => (
                        <th key={header.id} scope="col">
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className={selectedId === row.original.id ? "selected" : undefined}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
        <Inspector
          transaction={selected}
          onCorrect={() => setCorrecting(true)}
          correctButtonRef={correctionTriggerRef}
          onApproved={updateClassification}
        />
      </div>

      {correcting && selected ? (
        <CorrectionDialog
          transaction={selected}
          onClose={() => setCorrecting(false)}
          returnFocusRef={correctionTriggerRef}
          onSaved={(classification) => {
            setCorrecting(false);
            updateClassification(classification);
          }}
        />
      ) : null}
    </div>
  );
}

function Inspector({
  transaction,
  onCorrect,
  onApproved,
  correctButtonRef,
}: {
  transaction: Transaction | null;
  onCorrect: () => void;
  onApproved: (classification: Classification) => void;
  correctButtonRef: RefObject<HTMLButtonElement | null>;
}) {
  const approval = useMutation({
    mutationFn: () => api.approve(transaction!.id),
    onSuccess: onApproved,
  });

  return (
    <aside className="inspector" aria-labelledby="inspector-title">
      <div className="inspector-heading">
        <div>
          <p className="eyebrow">Selected item</p>
          <h2 id="inspector-title">Classification inspector</h2>
        </div>
      </div>
      {!transaction ? (
        <div className="inspector-empty">
          Select a transaction to inspect its evidence and make a decision.
        </div>
      ) : (
        <>
          <div className="inspector-amount">
            <span>{transaction.description}</span>
            <strong>{formatMoney(transaction.amount_minor, transaction.currency)}</strong>
            <small>{formatDate(transaction.transaction_date)}</small>
          </div>
          <dl className="detail-list">
            <div>
              <dt>Suggested account</dt>
              <dd>{transaction.classification?.account_number ?? "Unclassified"}</dd>
            </div>
            <div>
              <dt>Transaction type</dt>
              <dd>
                {transaction.classification
                  ? titleCase(transaction.classification.transaction_type)
                  : "Not available"}
              </dd>
            </div>
            <div>
              <dt>Risk</dt>
              <dd>{titleCase(transaction.risk)} risk</dd>
            </div>
            <div>
              <dt>Duplicate check</dt>
              <dd>{titleCase(transaction.duplicate_status)}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{titleCase(transaction.classification?.source ?? "unknown")}</dd>
            </div>
          </dl>
          <section className="evidence-block" aria-labelledby="evidence-title">
            <h3 id="evidence-title">Classification evidence</h3>
            <p>{transaction.classification?.explanation ?? "No evidence supplied."}</p>
          </section>
          {approval.isError ? <ErrorState error={approval.error} /> : null}
          <div className="inspector-actions">
            <button
              className="button primary"
              type="button"
              disabled={
                approval.isPending ||
                transaction.classification?.approval_status === "approved"
              }
              onClick={() => approval.mutate()}
            >
              <Check aria-hidden="true" />
              Approve classification
            </button>
            <button
              ref={correctButtonRef}
              className="button secondary"
              type="button"
              onClick={onCorrect}
            >
              Correct classification
            </button>
          </div>
        </>
      )}
    </aside>
  );
}

function CorrectionDialog({
  transaction,
  onClose,
  onSaved,
  returnFocusRef,
}: {
  transaction: Transaction;
  onClose: () => void;
  onSaved: (classification: Classification) => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
}) {
  const [account, setAccount] = useState(
    transaction.classification?.account_number ?? "6090",
  );
  const [transactionType, setTransactionType] = useState<TransactionType>(
    transaction.classification?.transaction_type ?? "operating_expense",
  );
  const [explanation, setExplanation] = useState("");
  const dialogRef = useRef<HTMLElement>(null);
  const initialFocusRef = useRef<HTMLSelectElement>(null);
  const correction = useMutation({
    mutationFn: () =>
      api.correct(transaction.id, {
        account_number: account,
        transaction_type: transactionType,
        explanation,
      }),
    onSuccess: onSaved,
  });

  useEffect(() => {
    const returnTarget = returnFocusRef.current;
    initialFocusRef.current?.focus();
    return () => {
      returnTarget?.focus();
    };
  }, [returnFocusRef]);

  const handleDialogKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        ref={dialogRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="correction-title"
        aria-describedby="correction-description"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={handleDialogKeyDown}
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">Human correction</p>
            <h2 id="correction-title">Correct classification</h2>
            <p id="correction-description" className="dialog-description">
              Choose the ledger account and record the accounting rationale.
            </p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close">
            <X aria-hidden="true" />
          </button>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            correction.mutate();
          }}
        >
          <label className="field">
            <span>Account</span>
            <select
              ref={initialFocusRef}
              value={account}
              onChange={(event) => setAccount(event.target.value)}
            >
              {accountOptions.map(([number, name]) => (
                <option key={number} value={number}>
                  {number} · {name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Transaction type</span>
            <select
              value={transactionType}
              onChange={(event) =>
                setTransactionType(event.target.value as TransactionType)
              }
            >
              {transactionTypes.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Reason for correction</span>
            <textarea
              required
              value={explanation}
              onChange={(event) => setExplanation(event.target.value)}
              placeholder="Record the accounting rationale."
            />
          </label>
          {correction.isError ? <ErrorState error={correction.error} /> : null}
          <div className="dialog-actions">
            <button className="button secondary" type="button" onClick={onClose}>
              Cancel
            </button>
            <button
              className="button primary"
              type="submit"
              disabled={!explanation.trim() || correction.isPending}
            >
              Save correction
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
