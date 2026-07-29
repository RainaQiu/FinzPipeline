import { z } from "zod";
import type {
  Classification,
  PnlReport,
  ProcessResult,
  QboStatus,
  QboSyncPlan,
  ReconciliationResult,
  TransactionPage,
  Upload,
  UploadMapping,
} from "../types";

const errorEnvelope = z.object({
  error: z.object({
    message: z.string(),
  }),
});

const qboStatusSchema = z
  .object({
    mode: z.literal("plan_only"),
    execution_authorized: z.literal(false),
    transaction_write_network_accessed: z.literal(false),
  })
  .strict();

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = errorEnvelope.safeParse(payload);
    throw new ApiError(
      parsed.success ? parsed.data.error.message : `Request failed (${response.status}).`,
      response.status,
    );
  }
  return payload as T;
}

function jsonInit(method: "POST" | "PATCH", body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export interface TransactionFilters {
  month?: string;
  approval?: string;
  account?: string;
  duplicate?: string;
  risk?: string;
  search?: string;
}

export const api = {
  transactions(filters: TransactionFilters = {}) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    params.set("limit", "250");
    return request<TransactionPage>(`/api/v1/transactions?${params}`);
  },

  upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request<Upload>("/api/v1/uploads", { method: "POST", body: form });
  },

  processUpload(uploadId: string, mapping: UploadMapping) {
    return request<ProcessResult>(
      `/api/v1/uploads/${uploadId}/process`,
      jsonInit("POST", mapping),
    );
  },

  approve(transactionId: string) {
    return request<Classification>(
      `/api/v1/transactions/${transactionId}/approve`,
      { method: "POST" },
    );
  },

  correct(
    transactionId: string,
    body: {
      account_number: string;
      transaction_type: string;
      explanation: string;
    },
  ) {
    return request<Classification>(
      `/api/v1/transactions/${transactionId}/correct`,
      jsonInit("POST", body),
    );
  },

  pnl(startDate: string, endDate: string) {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    return request<PnlReport>(`/api/v1/reports/pnl?${params}`);
  },

  pnlTransactions(account: string, startDate: string, endDate: string) {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    return request<{ account_number: string; items: TransactionPage["items"]; total: number }>(
      `/api/v1/reports/pnl/accounts/${account}/transactions?${params}`,
    );
  },

  async qboStatus(): Promise<QboStatus> {
    const payload = await request<unknown>("/api/v1/integrations/qbo/status");
    const parsed = qboStatusSchema.safeParse(payload);
    if (!parsed.success) {
      throw new Error(
        "QBO safety status could not be verified. Planning is blocked.",
      );
    }
    return parsed.data;
  },

  planQboSync(realmId: string) {
    return request<QboSyncPlan>(
      "/api/v1/integrations/qbo/sync",
      jsonInit("POST", { realm_id: realmId }),
    );
  },

  reconcile(startDate: string, endDate: string, qboReport: Record<string, unknown>) {
    return request<ReconciliationResult>(
      "/api/v1/reconciliations",
      jsonInit("POST", {
        start_date: startDate,
        end_date: endDate,
        qbo_report: qboReport,
      }),
    );
  },
};
