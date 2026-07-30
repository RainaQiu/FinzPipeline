export type TransactionType =
  | "revenue"
  | "cogs"
  | "operating_expense"
  | "refund"
  | "transfer"
  | "owner_activity"
  | "fixed_asset";

export interface Classification {
  id: string;
  transaction_id: string;
  account_number: string;
  transaction_type: TransactionType;
  source: string;
  confidence_basis_points: number;
  approval_status: string;
  needs_review: boolean;
  explanation: string;
  version: number;
  created_at: string;
  reviewed_at: string | null;
}

export interface Transaction {
  id: string;
  raw_record_id: string;
  bank_transaction_id: string;
  transaction_date: string;
  posted_date: string;
  description: string;
  description_normalized: string;
  amount_minor: number;
  currency: string;
  direction: "inflow" | "outflow";
  bank_account_number: string;
  duplicate_status: string;
  risk: "high" | "low";
  classification: Classification | null;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  offset: number;
  limit: number;
}

export interface Upload {
  id: string;
  filename: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  status: string;
  created_at: string;
}

export interface UploadMapping {
  columns: {
    transaction_id: string;
    transaction_date: string;
    posted_date?: string;
    description: string;
    amount: string;
    currency: string;
    bank_account: string;
  };
  sheet_name?: string;
  header_row: number;
  source_file_column?: string;
}

export interface ProcessResult {
  id: string;
  status: string;
  counts: {
    raw: number;
    unique: number;
    duplicates: number;
    transfer_pairs: number;
    classified: number;
  };
}

export interface PnlLine {
  account_number: string;
  account_name: string;
  total_minor: number;
  transaction_count: number;
  transaction_ids: string[];
}

export interface PnlReport {
  start_date: string;
  end_date: string;
  revenue_lines: PnlLine[];
  cogs_lines: PnlLine[];
  operating_expense_lines: PnlLine[];
  account_totals: Record<string, number>;
  totals: {
    revenue_minor: number;
    cogs_minor: number;
    gross_profit_minor: number;
    operating_expenses_minor: number;
    net_profit_minor: number;
  };
}

export interface ReconciliationLine {
  account_number: string;
  internal_minor: number;
  qbo_minor: number;
  difference_minor: number;
  status: string;
  diagnostic_candidates: string[];
}

export interface ReconciliationResult {
  id: string;
  status: string;
  start_date: string;
  end_date: string;
  lines: ReconciliationLine[];
  internal_totals: PnlReport["totals"];
  source?: "qbo_sandbox" | "local_payload";
  no_report_data?: boolean;
}

export interface QboStatus {
  mode: "demo_local" | "sandbox_read_only";
  connected: boolean;
  company_name: string | null;
  execution_authorized: false;
  transaction_write_network_accessed: boolean;
}

export interface QboSyncPlan {
  id: string;
  status: "planned";
  execution_authorized: false;
  planned_items: number;
  item_ids: string[];
}

export interface QboPrewrite {
  item_id: string;
  entity_type: string;
  status: string;
  amount: string | null;
  required_confirmation: string;
  writes_enabled: boolean;
}

export interface QboAccountPreflight {
  status: "ready";
  account_count: number;
  mapping: Record<string, string>;
}
